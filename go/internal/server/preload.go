package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/paths"
)

// Disk preload states. They are independent of the resident lifecycle.
const (
	preloadAbsent    = "absent"
	preloadLoading   = "preloading"
	preloadReady     = "preloaded"
	preloadUnloading = "unloading"
)

type preloadEntry struct {
	State     string    `json:"state"`
	JobID     string    `json:"job_id,omitempty"`
	UpdatedAt time.Time `json:"updated_at"`
	LastUsed  time.Time `json:"last_used,omitempty"`
}

type preloadFile struct {
	Models map[string]*preloadEntry `json:"models"`
}

// preloadStore persists explicit disk preload state so a daemon restart still
// knows which refs the operator prepared. Asset readiness itself is derived
// from the shared host cache; this store only records intent and in-flight jobs.
type preloadStore struct {
	mu     sync.Mutex
	path   string
	models map[string]*preloadEntry
	loaded bool
}

func newPreloadStore(path string) *preloadStore {
	return &preloadStore{path: path, models: map[string]*preloadEntry{}}
}

func (p *preloadStore) ensureLoaded() {
	if p.loaded {
		return
	}
	p.loaded = true
	if p.path == "" {
		return
	}
	blob, err := os.ReadFile(p.path)
	if err != nil {
		return
	}
	var file preloadFile
	if json.Unmarshal(blob, &file) != nil || file.Models == nil {
		return
	}
	p.models = file.Models
}

func (p *preloadStore) saveLocked() {
	if p.path == "" {
		return
	}
	blob, err := json.MarshalIndent(preloadFile{Models: p.models}, "", "  ")
	if err != nil {
		return
	}
	if err := os.MkdirAll(filepath.Dir(p.path), 0o755); err != nil {
		return
	}
	tmp := p.path + ".tmp"
	if err := os.WriteFile(tmp, append(blob, '\n'), 0o644); err != nil {
		return
	}
	_ = os.Rename(tmp, p.path)
}

func (p *preloadStore) state(refStr string) string {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ensureLoaded()
	if e, ok := p.models[refStr]; ok && e.State != "" {
		return e.State
	}
	return preloadAbsent
}

func (p *preloadStore) entry(refStr string) (preloadEntry, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ensureLoaded()
	e, ok := p.models[refStr]
	if !ok || e == nil {
		return preloadEntry{}, false
	}
	return *e, true
}

func (p *preloadStore) setState(refStr, state, jobID string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ensureLoaded()
	if state == preloadAbsent {
		delete(p.models, refStr)
		p.saveLocked()
		return
	}
	e := p.models[refStr]
	if e == nil {
		e = &preloadEntry{}
		p.models[refStr] = e
	}
	e.State = state
	e.JobID = jobID
	e.UpdatedAt = time.Now().UTC()
	p.saveLocked()
}

func (p *preloadStore) remove(refStr string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ensureLoaded()
	delete(p.models, refStr)
	p.saveLocked()
}

func (p *preloadStore) snapshot() map[string]preloadEntry {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ensureLoaded()
	out := make(map[string]preloadEntry, len(p.models))
	for refStr, e := range p.models {
		if e != nil {
			out[refStr] = *e
		}
	}
	return out
}

// preloads returns the process-wide preload store, creating the default one for
// servers constructed without New/NewFromConfig (mostly tests).
func (s *Server) preloads() *preloadStore {
	s.preloadMu.Lock()
	defer s.preloadMu.Unlock()
	if s.Preload == nil {
		s.Preload = newPreloadStore(filepath.Join(paths.Home(), "flashserver", "preload.json"))
	}
	return s.Preload
}

// preloadedAssets reports whether a cached model has everything preload
// guarantees. Native bundles have no runtime directory; Python bundles keep a
// non-empty runtime/venv.
func preloadedAssets(m host.Model) bool {
	if !m.BundleCached || !m.WeightsCached {
		return false
	}
	return m.RuntimeID == "" || m.RuntimeBytes > 0
}

// assetsReady checks the shared cache for one ref without touching the network.
func (s *Server) assetsReady(ctx context.Context, refStr string) bool {
	if s.Source == nil {
		return false
	}
	models, err := s.Source.Models(ctx)
	if err != nil {
		return false
	}
	for _, m := range models {
		if m.Ref == refStr {
			return preloadedAssets(m)
		}
	}
	return false
}

// reconcilePreloads drops stale intent after a daemon restart. Jobs do not
// survive a restart, so in-flight states become absent; a `preloaded` entry is
// kept only while its assets are still ready. Download markers on disk keep a
// later preload resumable.
func (s *Server) reconcilePreloads(ctx context.Context) {
	store := s.preloads()
	ready := map[string]bool{}
	if s.Source != nil {
		if models, err := s.Source.Models(ctx); err == nil {
			for _, m := range models {
				if preloadedAssets(m) {
					ready[m.Ref] = true
				}
			}
		}
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	store.ensureLoaded()
	changed := false
	for refStr, e := range store.models {
		if e == nil {
			delete(store.models, refStr)
			changed = true
			continue
		}
		switch e.State {
		case preloadReady:
			if !ready[refStr] {
				delete(store.models, refStr)
				changed = true
			}
		case preloadLoading, preloadUnloading:
			delete(store.models, refStr)
			changed = true
		}
	}
	if changed {
		store.saveLocked()
	}
}

// modelStatus is a management view of one ref: host cache facts plus disk and
// resident state.
type modelStatus struct {
	host.Model
	Preload        string     `json:"preload"`
	Resident       string     `json:"resident"`
	ActiveRequests int        `json:"active_requests"`
	LastUsed       *time.Time `json:"last_used,omitempty"`
}

// modelViews combines the shared cache view with preload intent and resident
// state. Refs that are only preloading/unloading still appear.
func (s *Server) modelViews(ctx context.Context, models []host.Model) []modelStatus {
	store := s.preloads()
	states := store.snapshot()
	resident := map[string]bool{}
	if s.Manager != nil {
		for _, inst := range s.Manager.List() {
			resident[inst.Ref] = true
		}
	}
	scheduled := map[string]ResidentInfo{}
	if s.Scheduler != nil {
		scheduled = s.Scheduler.States()
	}
	seen := map[string]bool{}
	out := make([]modelStatus, 0, len(models)+len(states))
	for _, m := range models {
		seen[m.Ref] = true
		state := preloadAbsent
		if e, ok := states[m.Ref]; ok && e.State != "" && e.State != preloadAbsent {
			state = e.State
		} else if preloadedAssets(m) {
			state = preloadReady
		}
		view := modelStatus{Model: m, Preload: state, Resident: "stopped"}
		if st, ok := scheduled[m.Ref]; ok {
			view.Resident = st.State
			view.ActiveRequests = st.ActiveRequests
			if !st.LastUsed.IsZero() {
				t := st.LastUsed
				view.LastUsed = &t
			}
		} else if resident[m.Ref] {
			view.Resident = "ready"
		}
		if e, ok := states[m.Ref]; ok && !e.LastUsed.IsZero() && view.LastUsed == nil {
			t := e.LastUsed
			view.LastUsed = &t
		}
		out = append(out, view)
	}
	for refStr, e := range states {
		if seen[refStr] || (e.State != preloadLoading && e.State != preloadReady && e.State != preloadUnloading) {
			continue
		}
		view := modelStatus{Model: host.Model{Ref: refStr}, Preload: e.State, Resident: "stopped"}
		if st, ok := scheduled[refStr]; ok {
			view.Resident = st.State
			view.ActiveRequests = st.ActiveRequests
			if !st.LastUsed.IsZero() {
				t := st.LastUsed
				view.LastUsed = &t
			}
		} else if resident[refStr] {
			view.Resident = "ready"
		}
		out = append(out, view)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Ref < out[j].Ref })
	return out
}

type preloadRequest struct {
	Ref string `json:"ref"`
}

// preloadModel serves POST /api/v1/models/preload: an asynchronous disk
// prepare (bundle, runtime/venv, weights). It never starts a serve process or
// reserves VRAM.
func (s *Server) preloadModel(w http.ResponseWriter, r *http.Request) {
	var req preloadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || strings.TrimSpace(req.Ref) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	refStr := strings.TrimSpace(req.Ref)
	if s.Puller == nil || s.Jobs == nil {
		writeError(w, http.StatusNotImplemented, errors.New("preload is not configured"))
		return
	}
	store := s.preloads()

	// Already complete on disk: preload is idempotent and needs no job.
	if s.assetsReady(r.Context(), refStr) {
		store.setState(refStr, preloadReady, "")
		fmt.Fprintf(LogSink(), "preload %s: already ready\n", refStr)
		writeJSON(w, http.StatusOK, map[string]any{"ref": refStr, "preload": preloadReady})
		return
	}

	store.mu.Lock()
	store.ensureLoaded()
	if e := store.models[refStr]; e != nil {
		switch e.State {
		case preloadLoading:
			jobID := e.JobID
			store.mu.Unlock()
			writeJSON(w, http.StatusAccepted, map[string]any{
				"ref": refStr, "preload": preloadLoading, "job_id": jobID, "state": "running",
			})
			return
		case preloadReady:
			store.mu.Unlock()
			writeJSON(w, http.StatusOK, map[string]any{"ref": refStr, "preload": preloadReady})
			return
		}
	}
	// Reserve the ref before starting the goroutine so concurrent requests share
	// one job. Jobs.Start only spawns a goroutine, which blocks on this mutex
	// when it tries to record completion.
	store.models[refStr] = &preloadEntry{State: preloadLoading, UpdatedAt: time.Now().UTC()}
	store.saveLocked()
	job := s.Jobs.Start(context.Background(), "preload", refStr, func(ctx context.Context, emit func(string, string)) error {
		_, err := s.Puller.Pull(ctx, refStr, host.PullOptions{
			VerifyWeights: true,
			Progress: func(ev host.PullEvent) {
				emit(ev.Phase, ev.Message)
			},
		})
		store.mu.Lock()
		defer store.mu.Unlock()
		store.ensureLoaded()
		if err != nil {
			delete(store.models, refStr)
			store.saveLocked()
			return err
		}
		store.models[refStr] = &preloadEntry{State: preloadReady, UpdatedAt: time.Now().UTC()}
		store.saveLocked()
		return nil
	})
	if e := store.models[refStr]; e != nil {
		e.JobID = job.ID
		store.saveLocked()
	}
	store.mu.Unlock()
	fmt.Fprintf(LogSink(), "preload %s: job %s\n", refStr, job.ID)
	writeJSON(w, http.StatusAccepted, map[string]any{
		"ref": refStr, "preload": preloadLoading, "job_id": job.ID, "state": job.State,
	})
}

type unloadRequest struct {
	Ref         string `json:"ref"`
	WaitSeconds int    `json:"wait_seconds"`
	Force       bool   `json:"force"`
}

// unloadModel serves POST /api/v1/models/unload. Resident stop and disk
// deletion are one management action: a busy model must be stopped (or forced)
// before its assets are removed.
func (s *Server) unloadModel(w http.ResponseWriter, r *http.Request) {
	var req unloadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || strings.TrimSpace(req.Ref) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	refStr := strings.TrimSpace(req.Ref)
	store := s.preloads()

	if s.modelBusy(refStr) {
		switch {
		case req.Force:
			if err := s.stopResident(r.Context(), refStr); err != nil {
				writeError(w, http.StatusInternalServerError, err)
				return
			}
		case req.WaitSeconds > 0:
			if !s.waitDrained(r.Context(), refStr, time.Duration(req.WaitSeconds)*time.Second) {
				writeModelBusy(w, refStr, "model still has active requests")
				return
			}
			if err := s.stopResident(r.Context(), refStr); err != nil {
				writeError(w, http.StatusInternalServerError, err)
				return
			}
		default:
			writeModelBusy(w, refStr, "model is resident or has active requests; stop it first or pass force")
			return
		}
	}

	store.setState(refStr, preloadUnloading, "")
	res, err := host.RemoveCachedRef(refStr)
	if err != nil {
		if errors.Is(err, host.ErrNotCached) {
			store.remove(refStr)
			fmt.Fprintf(LogSink(), "unload %s: not cached\n", refStr)
			writeJSON(w, http.StatusOK, map[string]any{
				"ref": refStr, "preload": preloadAbsent, "removed": false,
			})
			return
		}
		store.setState(refStr, preloadAbsent, "")
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	store.remove(refStr)
	fmt.Fprintf(LogSink(), "unload %s: removed %d bytes (shared bundle=%t weights=%t runtime=%t)\n",
		refStr, res.FreedBytes, res.SharedBundle, res.SharedWeights, res.SharedRuntime)
	writeJSON(w, http.StatusOK, map[string]any{
		"ref":            refStr,
		"preload":        preloadAbsent,
		"removed":        res.Removed,
		"freed_bytes":    res.FreedBytes,
		"shared_bundle":  res.SharedBundle,
		"shared_weights": res.SharedWeights,
		"shared_runtime": res.SharedRuntime,
	})
}

// modelBusy reports whether ref is resident or has active requests. A ready
// resident with no leases is still resident for unload purposes.
func (s *Server) modelBusy(refStr string) bool {
	if s.Scheduler != nil && s.Scheduler.Resident(refStr) {
		return true
	}
	return s.Manager != nil && s.Manager.Busy(refStr)
}

// stopResident stops a scheduler-owned resident or an admin-loaded instance.
func (s *Server) stopResident(ctx context.Context, refStr string) error {
	if s.Scheduler != nil && s.Scheduler.Resident(refStr) {
		return s.Scheduler.Stop(ctx, refStr)
	}
	if s.Manager != nil {
		return s.Manager.Unload(ctx, refStr)
	}
	return nil
}

// waitDrained waits for active leases to finish. A ready resident with no
// leases is already drained and may be stopped by the caller.
func (s *Server) waitDrained(ctx context.Context, refStr string, timeout time.Duration) bool {
	if s.Scheduler == nil {
		return true
	}
	deadline := time.Now().Add(timeout)
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for !s.Scheduler.Drained(refStr) {
		if time.Now().After(deadline) {
			return false
		}
		select {
		case <-ctx.Done():
			return false
		case <-ticker.C:
		}
	}
	return true
}

func writeModelBusy(w http.ResponseWriter, refStr, message string) {
	writeJSON(w, http.StatusConflict, map[string]any{
		"error": map[string]any{
			"message": message,
			"type":    "conflict",
			"code":    "model_busy",
			"model":   refStr,
		},
	})
}
