// Package server implements the local flashserver HTTP daemon.
package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/aodianyun/flashcli/go/internal/apps"
	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/version"
)

// Source supplies local cached state to the API.
type Source interface {
	Models(context.Context) ([]host.Model, error)
	Storage(context.Context) ([]host.Area, error)
}

type defaultSource struct{}

func (defaultSource) Models(context.Context) ([]host.Model, error) { return host.ListModels() }
func (defaultSource) Storage(context.Context) ([]host.Area, error) { return host.Storage(), nil }

// Server is the local flashserver daemon. It schedules models; inference runs
// in separate `flashcli serve` processes.
type Server struct {
	Addr          string
	Token         string
	Source        Source
	Puller        Puller
	Catalog       CatalogSource
	Jobs          *JobManager
	Manager       *Manager
	FlashcliBin   string
	GPU           func(context.Context) ([]gpu.Device, error)
	LogDir        string
	Started       time.Time
	ServeHost     string
	PublicHost    string
	ServeSettings *serveSettingsStore
	// AppService returns the shared application service (nil = default).
	AppService func() *apps.Service

	// VRAMHeadroomMiB is reserved on top of a bundle's min_vram_mib when
	// choosing a device. Zero uses the 512 MiB default.
	VRAMHeadroomMiB int

	// Demand-driven scheduler tuning and gateway behavior.
	IdleStopSeconds          int
	ResidentStartWaitSeconds int
	QueueTimeoutSeconds      int
	QueueMax                 int
	AutoPull                 bool
	CPUFallback              string
	// MaxUploadBytes bounds multipart inference uploads. Zero uses 256 MiB.
	MaxUploadBytes int64

	// Scheduler owns demand-driven resident lifecycle and leases.
	Scheduler *Scheduler

	// Preload persists explicit disk-preload intent across restarts.
	Preload *preloadStore

	pullBusy atomic.Bool

	preloadMu sync.Mutex

	histMu   sync.Mutex
	history  []GpuSample
	histOnce sync.Once

	cpuMu      sync.Mutex
	cpuPrev    []cpuCounters
	cpuUsage   float64
	cpuPerCore []float64

	wsMu      sync.Mutex
	wsClients map[*wsClient]struct{}
}

// New creates a server with the default local configuration.
func New(addr string) *Server {
	if addr == "" {
		addr = "127.0.0.1:8790"
	}
	gpuProbe := gpu.Probe
	store := newServeSettingsStore("")
	logDir := filepath.Join(paths.Home(), "logs", "serve")
	s := &Server{
		Addr:            addr,
		Source:          defaultSource{},
		Puller:          hostPuller{},
		Catalog:         flashhub.NewClient(),
		Jobs:            NewJobManager(),
		Manager:         NewManagerWithOptions(modelrun.FlashcliLauncher{LogDir: logDir}, ManagerOptions{GPU: gpuProbe, ServeSettings: store}),
		GPU:             gpuProbe,
		Started:         time.Now(),
		LogDir:          logDir,
		ServeSettings:   store,
		Preload:         newPreloadStore(filepath.Join(paths.Home(), "flashserver", "preload.json")),
		VRAMHeadroomMiB: 512,

		IdleStopSeconds:          600,
		ResidentStartWaitSeconds: 10,
		QueueTimeoutSeconds:      30,
		QueueMax:                 16,
		AutoPull:                 true,
		CPUFallback:              "no-gpu-runtime",
	}
	s.buildScheduler()
	return s
}

// buildScheduler (re)builds the resident scheduler from the current Manager and
// configuration. NewFromConfig calls it after replacing the Manager.
func (s *Server) buildScheduler() {
	maxLoaded := 0
	if s.Manager != nil {
		_, maxLoaded = s.Manager.Slots()
	}
	s.Scheduler = NewScheduler(s.Manager, SchedulerOptions{
		MaxLoaded:           maxLoaded,
		VRAMHeadroomMiB:     s.vramHeadroomMiB(),
		IdleStopSeconds:     s.IdleStopSeconds,
		QueueTimeoutSeconds: s.QueueTimeoutSeconds,
		QueueMax:            s.QueueMax,
		CPUDisabled:         s.CPUFallback == "disabled",
		Inventory:           s.inventory,
		Inspect:             inspectBundle,
		Notify:              s.residentEvent,
	})
}

func (s *Server) residentEvent(event string, data map[string]any) {
	if event == "" {
		return
	}
	fmt.Fprintf(LogSink(), "resident %s %v\n", event, data)
	s.broadcastWS(map[string]any{"type": "resident", "event": event, "data": data})
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	// Unauthenticated service endpoints.
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("GET /docs", s.apiDocs)
	mux.HandleFunc("GET /openapi.yaml", s.openapi)

	// Data plane: OpenAI-compatible gateway. Applications and the desktop use
	// only these routes for inference; they never see child serve endpoints.
	mux.HandleFunc("GET /v1/models", s.gatewayModels)
	for path, route := range gatewayJSONRoutes {
		mux.HandleFunc("POST "+path, s.gatewayJSONHandler(route.Capability, route.Upstream))
	}
	for path, route := range gatewayMultipartRoutes {
		mux.HandleFunc("POST "+path, s.gatewayMultipartHandler(route.Capability, route.Upstream))
	}
	mux.HandleFunc("GET /v1/realtime", s.serveRealtime)

	// Control plane: management API. Resident start/stop stays internal; these
	// routes configure disk state, applications, telemetry, and jobs.
	mux.HandleFunc("GET /api/v1/version", s.version)
	mux.HandleFunc("GET /api/v1/system", s.system)
	mux.HandleFunc("GET /api/v1/logs", s.logs)
	mux.HandleFunc("GET /api/v1/logs/download", s.downloadLogs)
	mux.HandleFunc("GET /api/v1/models", s.models)
	mux.HandleFunc("GET /api/v1/models/loaded", s.loadedModels)
	mux.HandleFunc("GET /api/v1/catalog", s.catalogRepos)
	mux.HandleFunc("GET /api/v1/catalog/tags", s.catalogTags)
	mux.HandleFunc("GET /api/v1/catalog/{id}", s.catalogRepo)
	mux.HandleFunc("GET /api/v1/storage", s.storage)
	mux.HandleFunc("GET /api/v1/mirror", s.mirrorStatus)
	mux.HandleFunc("POST /api/v1/mirror", s.setMirror)
	mux.HandleFunc("GET /api/v1/resources", s.resources)
	mux.HandleFunc("GET /api/v1/devices", s.devices)
	mux.HandleFunc("GET /api/v1/scheduler", s.scheduler)
	mux.HandleFunc("GET /api/v1/gpu", s.gpuStatus)
	mux.HandleFunc("GET /api/v1/gpu/history", s.gpuHistory)
	mux.HandleFunc("GET /api/v1/system/history", s.gpuHistory)
	mux.HandleFunc("GET /api/v1/ws", s.ws)
	mux.HandleFunc("POST /api/v1/pull", s.pull)
	mux.HandleFunc("GET /api/v1/jobs/{id}", s.job)
	mux.HandleFunc("GET /api/v1/jobs/{id}/events", s.jobEvents)
	mux.HandleFunc("POST /api/v1/jobs/{id}/cancel", s.cancelJob)
	mux.HandleFunc("POST /api/v1/models/load", s.loadModel)
	mux.HandleFunc("POST /api/v1/models/preload", s.preloadModel)
	mux.HandleFunc("POST /api/v1/models/unload", s.unloadModel)
	mux.HandleFunc("GET /api/v1/models/options", s.getModelOptions)
	mux.HandleFunc("PUT /api/v1/models/options", s.putModelOptions)
	mux.HandleFunc("DELETE /api/v1/models/options", s.deleteModelOptions)
	mux.HandleFunc("POST /api/v1/models/smoke", s.smokeModel)
	mux.HandleFunc("POST /api/v1/models/clean", s.cleanModels)
	mux.HandleFunc("POST /api/v1/storage/clean", s.cleanStorage)
	mux.HandleFunc("GET /api/v1/apps", s.appList)
	mux.HandleFunc("GET /api/v1/apps/installed", s.appInstalled)
	mux.HandleFunc("GET /api/v1/apps/{org}/{name}", s.appManifest)
	mux.HandleFunc("GET /api/v1/apps/{org}/{name}/status", s.appStatus)
	mux.HandleFunc("POST /api/v1/apps/{org}/{name}/install", s.appInstall)
	mux.HandleFunc("POST /api/v1/apps/{org}/{name}/prepare", s.appPrepare)
	mux.HandleFunc("POST /api/v1/apps/{org}/{name}/activate", s.appActivate)
	mux.HandleFunc("POST /api/v1/apps/{org}/{name}/deactivate", s.appDeactivate)
	mux.HandleFunc("DELETE /api/v1/apps/{org}/{name}", s.appUninstall)
	mux.HandleFunc("POST /api/v1/ui/chat", s.uiChat)

	// Local console assets.
	mux.HandleFunc("GET /ui/", s.ui)
	mux.HandleFunc("GET /", s.ui)
	return s.logRequests(s.authorize(mux))
}

func (s *Server) authorize(next http.Handler) http.Handler {
	if s.Token == "" {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" || r.URL.Path == "/" || r.URL.Path == "/docs" || r.URL.Path == "/openapi.yaml" || strings.HasPrefix(r.URL.Path, "/ui/") {
			next.ServeHTTP(w, r)
			return
		}
		token := r.Header.Get("Authorization")
		if token == "Bearer "+s.Token || r.Header.Get("X-Flashcli-Token") == s.Token {
			next.ServeHTTP(w, r)
			return
		}
		// Browser WebSocket clients cannot set headers; allow a query token.
		if r.URL.Path == "/api/v1/ws" && r.URL.Query().Get("token") == s.Token {
			next.ServeHTTP(w, r)
			return
		}
		writeJSON(w, http.StatusUnauthorized, map[string]any{"error": "unauthorized"})
	})
}

func (s *Server) Run(ctx context.Context) error {
	// Persist the service log (API calls, job steps, scripts) so a restart
	// still shows earlier activity.
	InitLogFile(filepath.Join(paths.Home(), "logs", "flashserver.log"))
	s.startGPUHistory(ctx)
	s.reconcilePreloads(ctx)
	if s.Scheduler != nil {
		s.Scheduler.Start(ctx)
	}
	go s.forwardJobs(ctx)
	// Go treats the IPv4 wildcard 0.0.0.0 as a wildcard and may bind a
	// dual-stack socket. Windows' WSL localhost relay then exposes only ::1,
	// so explicit 127.0.0.1 clients fail. Pin the socket family to the
	// configured wildcard.
	network := "tcp"
	if host, _, err := net.SplitHostPort(s.Addr); err == nil {
		switch host {
		case "0.0.0.0":
			network = "tcp4"
		case "::", "[::]":
			network = "tcp6"
		}
	}
	ln, err := net.Listen(network, s.Addr)
	if err != nil {
		return err
	}
	srv := &http.Server{
		Handler:           s.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdownCtx)
		if s.Manager != nil {
			s.Manager.Close(shutdownCtx)
		}
	}()
	s.restoreOnStart(ctx)
	log.Printf("flashserver %s listening on http://%s", version.Version, ln.Addr())
	err = srv.Serve(ln)
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "version": version.Version})
}

func (s *Server) version(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"version": version.Version})
}

func (s *Server) models(w http.ResponseWriter, r *http.Request) {
	var models []host.Model
	if s.Source != nil {
		var err error
		models, err = s.Source.Models(r.Context())
		if err != nil {
			writeError(w, http.StatusInternalServerError, err)
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"models": s.modelViews(r.Context(), models),
		"loaded": s.loaded(),
	})
}

func (s *Server) loadedModels(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"models": s.loaded()})
}

func (s *Server) loaded() []InstanceInfo {
	if s.Manager == nil {
		return []InstanceInfo{}
	}
	return s.Manager.List()
}

func (s *Server) resources(w http.ResponseWriter, r *http.Request) {
	out := map[string]any{"gpu": []any{}, "loaded": s.loaded()}
	if s.Manager != nil {
		loadedCount, maxLoaded := s.Manager.Slots()
		out["loaded_count"] = loadedCount
		out["max_loaded"] = maxLoaded
	}
	if s.GPU != nil {
		devices, err := s.GPU(r.Context())
		if err != nil {
			out["gpu_error"] = err.Error()
		} else {
			out["gpu"] = devices
		}
	}
	writeJSON(w, http.StatusOK, out)
}

func (s *Server) gpuStatus(w http.ResponseWriter, r *http.Request) {
	if s.GPU == nil {
		writeJSON(w, http.StatusOK, map[string]any{"devices": []any{}, "processes": []any{}})
		return
	}
	devices, err := s.GPU(r.Context())
	if err != nil {
		writeError(w, http.StatusServiceUnavailable, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"devices": devices, "processes": gpuProcesses(r.Context())})
}

func (s *Server) storage(w http.ResponseWriter, r *http.Request) {
	areas, err := s.Source.Storage(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"areas": areas})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, err error) {
	writeJSON(w, status, map[string]any{"error": err.Error()})
}
