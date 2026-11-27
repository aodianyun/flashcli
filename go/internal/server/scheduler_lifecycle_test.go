package server

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/manifest"
)

// lifecycleLauncher starts fake serve processes and can hold a ref in the
// starting state until its healthy channel is closed.
type lifecycleLauncher struct {
	mu    sync.Mutex
	calls int
	block map[string]chan struct{}
	fail  map[string]error
	procs map[string]*fakeServe
}

func (l *lifecycleLauncher) Start(ctx context.Context, refStr string, port int) (ServeProcess, error) {
	return l.StartWithOptions(ctx, refStr, LoadOptions{Port: port})
}

func (l *lifecycleLauncher) StartWithOptions(_ context.Context, refStr string, opts LoadOptions) (ServeProcess, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.calls++
	if err := l.fail[refStr]; err != nil {
		return nil, err
	}
	if l.procs == nil {
		l.procs = map[string]*fakeServe{}
	}
	p := &fakeServe{ref: refStr, endpoint: "http://127.0.0.1:1", healthy: l.block[refStr]}
	l.procs[refStr] = p
	return p, nil
}

func (l *lifecycleLauncher) callCount() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.calls
}

func (l *lifecycleLauncher) process(refStr string) *fakeServe {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.procs[refStr]
}

func newSchedulerWith(t *testing.T, launcher Launcher, manifests map[string]*manifest.Manifest, inventory func(context.Context) DeviceInventory, opts SchedulerOptions) *Scheduler {
	t.Helper()
	inspect := func(refStr string) (BundleInfo, error) {
		m, ok := manifests[refStr]
		if !ok {
			return BundleInfo{}, errors.New("unknown ref " + refStr)
		}
		return BundleInfo{Name: refStr, Manifest: m}, nil
	}
	manager := NewManagerWithOptions(launcher, ManagerOptions{Inspect: inspect})
	opts.Inspect = inspect
	opts.Inventory = inventory
	if opts.IdleStopSeconds == 0 {
		opts.IdleStopSeconds = 3600
	}
	return NewScheduler(manager, opts)
}

func singleGPUInventory(freeBytes int64) DeviceInventory {
	return inventoryFrom([]gpu.Device{{
		Index: 0, Name: "RTX 4060", MemoryTotal: 8 << 30, MemoryFree: freeBytes,
		ComputeCap: "8.9",
	}}, "")
}

type mutableInventory struct {
	mu  sync.Mutex
	inv DeviceInventory
}

func (m *mutableInventory) Get(context.Context) DeviceInventory {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.inv
}

func (m *mutableInventory) SetFree(bytes int64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for i := range m.inv.Devices {
		if m.inv.Devices[i].Kind == "cuda" {
			m.inv.Devices[i].MemoryFreeBytes = bytes
		}
	}
}

func vramManifest(t *testing.T, mib int64) *manifest.Manifest {
	t.Helper()
	return placementManifest(t, []string{"sm89-cu124-linux-x86_64-py312"}, map[string]any{"min_vram_mib": int(mib)})
}

func waitUntil(t *testing.T, timeout time.Duration, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestSchedulerUnlimitedSlotsAdmitMultipleModels(t *testing.T) {
	launcher := &lifecycleLauncher{}
	a, b := "a:1", "b:1"
	manifests := map[string]*manifest.Manifest{a: vramManifest(t, 4096), b: vramManifest(t, 4096)}
	inv := &mutableInventory{inv: singleGPUInventory(12 << 30)}
	s := newSchedulerWith(t, launcher, manifests, inv.Get, SchedulerOptions{VRAMHeadroomMiB: 512})

	leaseA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatalf("acquire a: %v", err)
	}
	leaseB, err := s.Acquire(context.Background(), b)
	if err != nil {
		t.Fatalf("acquire b with max_loaded=0: %v", err)
	}
	if launcher.callCount() != 2 {
		t.Fatalf("launcher calls = %d, want 2", launcher.callCount())
	}
	states := s.States()
	if states[a].State != residentBusy || states[b].State != residentBusy {
		t.Fatalf("states = %+v", states)
	}
	leaseA.Release()
	leaseB.Release()
}

func TestSchedulerResourceExhaustionWithoutSlotLimit(t *testing.T) {
	launcher := &lifecycleLauncher{}
	a, b := "a:1", "b:1"
	manifests := map[string]*manifest.Manifest{a: vramManifest(t, 4096), b: vramManifest(t, 4096)}
	inv := &mutableInventory{inv: singleGPUInventory(6 << 30)}
	s := newSchedulerWith(t, launcher, manifests, inv.Get, SchedulerOptions{VRAMHeadroomMiB: 512})

	leaseA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatalf("acquire a: %v", err)
	}
	defer leaseA.Release()

	// The resident now occupies VRAM; the next probe reports the reduced free
	// memory. max_loaded=0 must still reject the second model.
	inv.SetFree(3 << 30)
	_, err = s.Acquire(context.Background(), b)
	var pe *PlacementError
	if !errors.As(err, &pe) || pe.Code != "no_placement" || pe.Reason != reasonResourceExhausted {
		t.Fatalf("error = %v, want no_placement/resource_exhausted", err)
	}
	if launcher.callCount() != 1 {
		t.Fatalf("launcher calls = %d, want 1", launcher.callCount())
	}
}

func TestSchedulerNoCompatibleRuntimeDoesNotQueue(t *testing.T) {
	launcher := &lifecycleLauncher{}
	a, b := "a:1", "b:1"
	manifests := map[string]*manifest.Manifest{
		a: vramManifest(t, 1024),
		b: placementManifest(t, []string{"sm86-cu124-linux-x86_64-py312"}, nil),
	}
	inv := &mutableInventory{inv: singleGPUInventory(12 << 30)}
	s := newSchedulerWith(t, launcher, manifests, inv.Get, SchedulerOptions{
		QueueTimeoutSeconds: 5, VRAMHeadroomMiB: 512,
	})

	leaseA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatal(err)
	}
	defer leaseA.Release()

	start := time.Now()
	_, err = s.Acquire(context.Background(), b)
	elapsed := time.Since(start)
	var pe *PlacementError
	if !errors.As(err, &pe) || pe.Code != "no_placement" || pe.Reason != reasonNoCompatibleRuntime {
		t.Fatalf("error = %v, want no_placement/no_compatible_runtime", err)
	}
	if elapsed > time.Second {
		t.Fatalf("incompatible model waited %s, want immediate failure", elapsed)
	}
	if waiters := s.Snapshot().Waiters; waiters != 0 {
		t.Fatalf("waiters = %d, want 0", waiters)
	}
}

func TestSchedulerReservesVRAMWhileStarting(t *testing.T) {
	launcher := &lifecycleLauncher{block: map[string]chan struct{}{}}
	a, b := "a:1", "b:1"
	block := make(chan struct{})
	launcher.block[a] = block
	manifests := map[string]*manifest.Manifest{a: vramManifest(t, 4096), b: vramManifest(t, 4096)}
	inv := &mutableInventory{inv: singleGPUInventory(6 << 30)}
	s := newSchedulerWith(t, launcher, manifests, inv.Get, SchedulerOptions{VRAMHeadroomMiB: 512})

	leaseCh := make(chan *Lease, 1)
	errCh := make(chan error, 1)
	go func() {
		lease, err := s.Acquire(context.Background(), a)
		if err != nil {
			errCh <- err
			return
		}
		leaseCh <- lease
	}()
	waitUntil(t, 3*time.Second, "a to start", func() bool {
		return s.States()[a].State == residentStarting
	})
	waitUntil(t, 3*time.Second, "a launcher", func() bool {
		return launcher.callCount() == 1
	})

	// a is not visible to nvidia-smi yet, but its reservation must already
	// count against the GPU so b cannot be admitted into the same memory.
	_, err := s.Acquire(context.Background(), b)
	var pe *PlacementError
	if !errors.As(err, &pe) || pe.Code != "no_placement" || pe.Reason != reasonResourceExhausted {
		t.Fatalf("b error = %v, want no_placement/resource_exhausted", err)
	}
	if launcher.callCount() != 1 {
		t.Fatalf("launcher calls = %d, want 1", launcher.callCount())
	}

	close(block)
	select {
	case lease := <-leaseCh:
		lease.Release()
	case err := <-errCh:
		t.Fatalf("acquire a: %v", err)
	case <-time.After(5 * time.Second):
		t.Fatal("a did not finish starting")
	}
}

func TestSchedulerQueueTimeoutReturnsResourceError(t *testing.T) {
	launcher := &lifecycleLauncher{}
	a, b := "a:1", "b:1"
	manifests := map[string]*manifest.Manifest{a: vramManifest(t, 1024), b: vramManifest(t, 1024)}
	inv := &mutableInventory{inv: singleGPUInventory(12 << 30)}
	s := newSchedulerWith(t, launcher, manifests, inv.Get, SchedulerOptions{
		MaxLoaded: 1, QueueTimeoutSeconds: 1, VRAMHeadroomMiB: 512,
	})

	leaseA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatal(err)
	}
	defer leaseA.Release()

	start := time.Now()
	_, err = s.Acquire(context.Background(), b)
	elapsed := time.Since(start)
	var pe *PlacementError
	if !errors.As(err, &pe) || pe.Code != "no_placement" || pe.Reason != reasonResourceExhausted {
		t.Fatalf("error = %v, want no_placement/resource_exhausted", err)
	}
	if elapsed < 800*time.Millisecond || elapsed > 3*time.Second {
		t.Fatalf("queue wait = %s, want about 1s", elapsed)
	}
	if launcher.callCount() != 1 {
		t.Fatalf("launcher calls = %d, want 1", launcher.callCount())
	}
}

func TestSchedulerQueueFullWhileResidentIsBusy(t *testing.T) {
	launcher := &lifecycleLauncher{}
	a, b, c := "a:1", "b:1", "c:1"
	manifests := map[string]*manifest.Manifest{
		a: vramManifest(t, 1024), b: vramManifest(t, 1024), c: vramManifest(t, 1024),
	}
	inv := &mutableInventory{inv: singleGPUInventory(12 << 30)}
	s := newSchedulerWith(t, launcher, manifests, inv.Get, SchedulerOptions{
		MaxLoaded: 1, QueueTimeoutSeconds: 10, QueueMax: 1, VRAMHeadroomMiB: 512,
	})

	leaseA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatal(err)
	}
	defer leaseA.Release()

	bCh := make(chan error, 1)
	go func() {
		lease, err := s.Acquire(context.Background(), b)
		if lease != nil {
			lease.Release()
		}
		bCh <- err
	}()
	waitUntil(t, 3*time.Second, "b to queue", func() bool {
		return s.Snapshot().Waiters == 1
	})

	_, err = s.Acquire(context.Background(), c)
	var pe *PlacementError
	if !errors.As(err, &pe) || pe.Code != "queue_full" {
		t.Fatalf("c error = %v, want queue_full", err)
	}

	leaseA.Release()
	select {
	case err := <-bCh:
		if err != nil {
			t.Fatalf("queued b: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("queued b did not finish")
	}
}

func TestSchedulerQueuedAcquireCanceled(t *testing.T) {
	launcher := &lifecycleLauncher{}
	a, b := "a:1", "b:1"
	manifests := map[string]*manifest.Manifest{a: vramManifest(t, 1024), b: vramManifest(t, 1024)}
	inv := &mutableInventory{inv: singleGPUInventory(12 << 30)}
	s := newSchedulerWith(t, launcher, manifests, inv.Get, SchedulerOptions{
		MaxLoaded: 1, QueueTimeoutSeconds: 10, VRAMHeadroomMiB: 512,
	})

	leaseA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatal(err)
	}
	defer leaseA.Release()

	ctx, cancel := context.WithCancel(context.Background())
	errCh := make(chan error, 1)
	go func() {
		lease, err := s.Acquire(ctx, b)
		if lease != nil {
			lease.Release()
		}
		errCh <- err
	}()
	waitUntil(t, 3*time.Second, "b to queue", func() bool {
		return s.Snapshot().Waiters == 1
	})
	cancel()
	select {
	case err := <-errCh:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error = %v, want context.Canceled", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("canceled acquire did not return")
	}
	waitUntil(t, 3*time.Second, "queue to drain", func() bool {
		return s.Snapshot().Waiters == 0
	})
	if launcher.callCount() != 1 {
		t.Fatalf("launcher calls = %d, want 1", launcher.callCount())
	}
}

func TestSchedulerIdleStopSkipsBusyResident(t *testing.T) {
	launcher := &lifecycleLauncher{}
	refStr := "a:1"
	s := newSchedulerWith(t, launcher,
		map[string]*manifest.Manifest{refStr: vramManifest(t, 1024)},
		(&mutableInventory{inv: singleGPUInventory(12 << 30)}).Get,
		SchedulerOptions{IdleStopSeconds: 1, VRAMHeadroomMiB: 512})

	lease, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatal(err)
	}
	old := time.Now().Add(-2 * time.Minute)
	s.mu.Lock()
	s.residents[refStr].lastUsed = old
	s.mu.Unlock()
	s.reap()
	if !s.Resident(refStr) {
		t.Fatal("busy resident was reaped")
	}

	lease.Release()
	s.mu.Lock()
	s.residents[refStr].lastUsed = old
	s.mu.Unlock()
	s.reap()
	if s.Resident(refStr) {
		t.Fatal("idle resident was not reaped")
	}
}

func TestSchedulerStopDuringStartDoesNotLeak(t *testing.T) {
	launcher := &lifecycleLauncher{block: map[string]chan struct{}{}}
	refStr := "a:1"
	block := make(chan struct{})
	launcher.block[refStr] = block
	s := newSchedulerWith(t, launcher,
		map[string]*manifest.Manifest{refStr: vramManifest(t, 1024)},
		(&mutableInventory{inv: singleGPUInventory(12 << 30)}).Get,
		SchedulerOptions{VRAMHeadroomMiB: 512})

	acquireErr := make(chan error, 1)
	go func() {
		lease, err := s.Acquire(context.Background(), refStr)
		if lease != nil {
			lease.Release()
		}
		acquireErr <- err
	}()
	waitUntil(t, 3*time.Second, "start", func() bool {
		return s.States()[refStr].State == residentStarting
	})

	stopDone := make(chan error, 1)
	go func() { stopDone <- s.Stop(context.Background(), refStr) }()
	close(block)

	select {
	case err := <-acquireErr:
		if err == nil {
			t.Fatal("acquire should fail when the start is stopped")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("acquire did not return")
	}
	select {
	case err := <-stopDone:
		if err != nil {
			t.Fatalf("stop: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("stop did not return")
	}

	if s.Resident(refStr) {
		t.Fatal("stopped start left a resident")
	}
	if got := len(s.manager.List()); got != 0 {
		t.Fatalf("manager instances = %d, want 0", got)
	}

	// The next request starts exactly one fresh process.
	lease, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatalf("acquire after stopped start: %v", err)
	}
	lease.Release()
	if launcher.callCount() != 2 {
		t.Fatalf("launcher calls = %d, want 2", launcher.callCount())
	}
}

func TestSchedulerStopDuringStartCancelsSlowHealthWait(t *testing.T) {
	launcher := &lifecycleLauncher{block: map[string]chan struct{}{}}
	refStr := "a:1"
	block := make(chan struct{}) // never closed: the health wait must be cancelled
	launcher.block[refStr] = block
	s := newSchedulerWith(t, launcher,
		map[string]*manifest.Manifest{refStr: vramManifest(t, 1024)},
		(&mutableInventory{inv: singleGPUInventory(12 << 30)}).Get,
		SchedulerOptions{VRAMHeadroomMiB: 512})

	acquireErr := make(chan error, 1)
	go func() {
		lease, err := s.Acquire(context.Background(), refStr)
		if lease != nil {
			lease.Release()
		}
		acquireErr <- err
	}()
	waitUntil(t, 3*time.Second, "start", func() bool {
		return s.States()[refStr].State == residentStarting
	})
	waitUntil(t, 3*time.Second, "launcher", func() bool {
		return launcher.callCount() == 1
	})

	stopDone := make(chan error, 1)
	go func() { stopDone <- s.Stop(context.Background(), refStr) }()
	select {
	case err := <-stopDone:
		if err != nil {
			t.Fatalf("stop: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("force stop did not cancel the health wait")
	}
	select {
	case err := <-acquireErr:
		if err == nil {
			t.Fatal("acquire should fail when the start is cancelled")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("acquire did not return")
	}
	if s.Resident(refStr) {
		t.Fatal("cancelled start left a resident")
	}
	if got := len(s.manager.List()); got != 0 {
		t.Fatalf("manager instances = %d, want 0", got)
	}
}

func TestSchedulerCrashWhileLeasedStartsOnceAndStaleLeaseIsIgnored(t *testing.T) {
	launcher := &lifecycleLauncher{}
	refStr := "a:1"
	s := newSchedulerWith(t, launcher,
		map[string]*manifest.Manifest{refStr: vramManifest(t, 1024)},
		(&mutableInventory{inv: singleGPUInventory(12 << 30)}).Get,
		SchedulerOptions{VRAMHeadroomMiB: 512})

	first, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatal(err)
	}
	launcher.process(refStr).Stop(context.Background())

	second, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatalf("acquire after crash: %v", err)
	}
	if launcher.callCount() != 2 {
		t.Fatalf("launcher calls = %d, want 2", launcher.callCount())
	}

	// The stale lease belongs to the dead generation and must not release the
	// new generation's lease.
	first.Release()
	if got := s.ActiveRequests(refStr); got != 1 {
		t.Fatalf("active requests after stale release = %d, want 1", got)
	}
	second.Release()
	if got := s.ActiveRequests(refStr); got != 0 {
		t.Fatalf("active requests = %d, want 0", got)
	}
}

func TestSchedulerStopReleasesLeasesAndAllowsRestart(t *testing.T) {
	launcher := &lifecycleLauncher{}
	refStr := "a:1"
	s := newSchedulerWith(t, launcher,
		map[string]*manifest.Manifest{refStr: vramManifest(t, 1024)},
		(&mutableInventory{inv: singleGPUInventory(12 << 30)}).Get,
		SchedulerOptions{VRAMHeadroomMiB: 512})

	lease, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Stop(context.Background(), refStr); err != nil {
		t.Fatal(err)
	}
	if s.Resident(refStr) {
		t.Fatal("resident survived force stop")
	}
	if got := s.ActiveRequests(refStr); got != 0 {
		t.Fatalf("active requests = %d, want 0", got)
	}
	if got := len(s.manager.List()); got != 0 {
		t.Fatalf("manager instances = %d, want 0", got)
	}
	lease.Release()

	next, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatalf("acquire after force stop: %v", err)
	}
	next.Release()
	if launcher.callCount() != 2 {
		t.Fatalf("launcher calls = %d, want 2", launcher.callCount())
	}
}

func TestUnloadActiveSchedulerLeaseWaitOrForce(t *testing.T) {
	s := newFlowServer(t, &staticLauncher{endpoint: "http://127.0.0.1:1"})
	h := s.Handler()
	refStr := "demo:1"

	lease, err := s.Scheduler.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatal(err)
	}

	rec, body := call(t, h, http.MethodPost, "/api/v1/models/unload", `{"ref":"demo:1"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("unload busy = %d: %s", rec.Code, rec.Body.String())
	}
	if errObj, _ := body["error"].(map[string]any); errObj["code"] != "model_busy" {
		t.Fatalf("error = %v", body)
	}

	// wait_seconds still times out while the lease is held.
	rec, _ = call(t, h, http.MethodPost, "/api/v1/models/unload", `{"ref":"demo:1","wait_seconds":1}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("unload wait = %d: %s", rec.Code, rec.Body.String())
	}

	// Releasing the lease lets the same request finish.
	go func() {
		time.Sleep(150 * time.Millisecond)
		lease.Release()
	}()
	rec, body = call(t, h, http.MethodPost, "/api/v1/models/unload", `{"ref":"demo:1","wait_seconds":2}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("unload after release = %d: %s", rec.Code, rec.Body.String())
	}
	if body["preload"] != preloadAbsent {
		t.Fatalf("unload body = %v", body)
	}
	if s.Scheduler.Resident(refStr) {
		t.Fatal("resident survived unload")
	}

	// force stops a busy resident and releases its lease.
	busy, err := s.Scheduler.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatal(err)
	}
	rec, _ = call(t, h, http.MethodPost, "/api/v1/models/unload", `{"ref":"demo:1","force":true}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("force unload = %d: %s", rec.Code, rec.Body.String())
	}
	if s.Scheduler.Resident(refStr) {
		t.Fatal("resident survived force unload")
	}
	if got := len(s.Manager.List()); got != 0 {
		t.Fatalf("manager instances = %d, want 0", got)
	}
	busy.Release()
}

func TestSchedulerScheduledResidentIsNotPersisted(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "models.json")
	inspect := func(refStr string) (BundleInfo, error) {
		return BundleInfo{Name: refStr, Manifest: vramManifest(t, 1024)}, nil
	}
	launcher := &lifecycleLauncher{}
	manager := NewManagerWithOptions(launcher, ManagerOptions{Inspect: inspect, StatePath: statePath})
	inv := &mutableInventory{inv: singleGPUInventory(12 << 30)}
	s := NewScheduler(manager, SchedulerOptions{
		Inspect: inspect, Inventory: inv.Get, IdleStopSeconds: 3600, VRAMHeadroomMiB: 512,
	})

	lease, err := s.Acquire(context.Background(), "a:1")
	if err != nil {
		t.Fatal(err)
	}
	lease.Release()

	if blob, err := os.ReadFile(statePath); err == nil {
		var state modelsStateFile
		if len(blob) > 0 {
			if err := json.Unmarshal(blob, &state); err != nil {
				t.Fatal(err)
			}
		}
		if len(state.Models) != 0 {
			t.Fatalf("scheduled resident was persisted: %v", state.Models)
		}
	}

	second := &lifecycleLauncher{}
	restored := NewManagerWithOptions(second, ManagerOptions{Inspect: inspect, StatePath: statePath})
	if errs := restored.RestoreModels(context.Background()); len(errs) != 0 {
		t.Fatalf("restore errors = %v", errs)
	}
	if second.callCount() != 0 {
		t.Fatalf("restore started %d scheduled models", second.callCount())
	}
}
