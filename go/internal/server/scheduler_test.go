package server

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
)

type recordingLauncher struct {
	mu    sync.Mutex
	calls int
	envs  map[string][]string
	procs map[string]*fakeServe
	err   error
}

func (l *recordingLauncher) Start(ctx context.Context, refStr string, port int) (ServeProcess, error) {
	return l.StartWithOptions(ctx, refStr, modelrun.LoadOptions{Port: port})
}

func (l *recordingLauncher) StartWithOptions(_ context.Context, refStr string, opts modelrun.LoadOptions) (ServeProcess, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.calls++
	if l.envs == nil {
		l.envs = map[string][]string{}
	}
	l.envs[refStr] = append([]string(nil), opts.Env...)
	if l.err != nil {
		return nil, l.err
	}
	if l.procs == nil {
		l.procs = map[string]*fakeServe{}
	}
	p := &fakeServe{ref: refStr, endpoint: "http://127.0.0.1:1"}
	l.procs[refStr] = p
	return p, nil
}

func (l *recordingLauncher) callCount() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.calls
}

func (l *recordingLauncher) env(refStr string) []string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return append([]string(nil), l.envs[refStr]...)
}

func (l *recordingLauncher) process(refStr string) *fakeServe {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.procs[refStr]
}

func newTestScheduler(t *testing.T, launcher Launcher, manifests map[string]*manifest.Manifest, inv DeviceInventory, opts SchedulerOptions) *Scheduler {
	t.Helper()
	inspect := func(refStr string) (BundleInfo, error) {
		m, ok := manifests[refStr]
		if !ok {
			return BundleInfo{}, fmt.Errorf("unknown ref %q", refStr)
		}
		return BundleInfo{Name: refStr, Manifest: m}, nil
	}
	manager := NewManagerWithOptions(launcher, ManagerOptions{Inspect: inspect})
	opts.Inspect = inspect
	opts.Inventory = func(context.Context) DeviceInventory { return inv }
	if opts.IdleStopSeconds == 0 {
		opts.IdleStopSeconds = 3600
	}
	return NewScheduler(manager, opts)
}

func gpuManifest(t *testing.T) *manifest.Manifest {
	return placementManifest(t, []string{"sm89-cu124-linux-x86_64-py312"}, map[string]any{"min_vram_mib": 1024})
}

func TestSchedulerSharesStartAndTracksLeases(t *testing.T) {
	launcher := &recordingLauncher{}
	refStr := "demo:1"
	s := newTestScheduler(t, launcher,
		map[string]*manifest.Manifest{refStr: gpuManifest(t)},
		twoGPUInventory(28<<30),
		SchedulerOptions{})
	defer s.Stop(context.Background(), refStr)

	var wg sync.WaitGroup
	leases := make([]*Lease, 2)
	for i := range leases {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			lease, err := s.Acquire(context.Background(), refStr)
			if err != nil {
				t.Errorf("acquire: %v", err)
				return
			}
			leases[i] = lease
		}(i)
	}
	wg.Wait()
	if launcher.callCount() != 1 {
		t.Fatalf("launcher calls = %d, want 1", launcher.callCount())
	}
	info := s.States()[refStr]
	if info.State != residentBusy || info.ActiveRequests != 2 {
		t.Fatalf("resident = %+v", info)
	}
	env := launcher.env(refStr)
	if len(env) != 1 || env[0] != "CUDA_VISIBLE_DEVICES=0" {
		t.Fatalf("env = %v", env)
	}

	leases[0].Release()
	if info := s.States()[refStr]; info.ActiveRequests != 1 || info.State != residentBusy {
		t.Fatalf("after one release: %+v", info)
	}
	leases[1].Release()
	if info := s.States()[refStr]; info.ActiveRequests != 0 || info.State != residentReady {
		t.Fatalf("after both releases: %+v", info)
	}
}

func TestSchedulerEvictsLRUIdleOnly(t *testing.T) {
	launcher := &recordingLauncher{}
	a, b := "a:1", "b:1"
	manifests := map[string]*manifest.Manifest{a: gpuManifest(t), b: gpuManifest(t)}
	s := newTestScheduler(t, launcher, manifests, twoGPUInventory(28<<30), SchedulerOptions{MaxLoaded: 1})
	defer s.Stop(context.Background(), a)

	leaseA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatal(err)
	}
	leaseA.Release()

	leaseB, err := s.Acquire(context.Background(), b)
	if err != nil {
		t.Fatalf("acquire b: %v", err)
	}
	leaseB.Release()
	if s.Resident(a) {
		t.Fatal("idle a should have been evicted for b")
	}
	if !s.Resident(b) {
		t.Fatal("b should be resident")
	}

	// A busy resident is never evicted.
	busyA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatal(err)
	}
	defer busyA.Release()
	if _, err := s.Acquire(context.Background(), b); err == nil {
		t.Fatal("b should not start while the slot is held by a busy resident")
	}
	var pe *PlacementError
	if _, err := s.Acquire(context.Background(), b); !errors.As(err, &pe) || pe.Code != "no_placement" {
		t.Fatalf("error = %v", err)
	}
}

func TestSchedulerQueuesUntilLeaseReleased(t *testing.T) {
	launcher := &recordingLauncher{}
	a, b := "a:1", "b:1"
	manifests := map[string]*manifest.Manifest{a: gpuManifest(t), b: gpuManifest(t)}
	s := newTestScheduler(t, launcher, manifests, twoGPUInventory(28<<30), SchedulerOptions{
		MaxLoaded: 1, QueueTimeoutSeconds: 2,
	})
	defer s.Stop(context.Background(), a)

	leaseA, err := s.Acquire(context.Background(), a)
	if err != nil {
		t.Fatal(err)
	}
	go func() {
		time.Sleep(150 * time.Millisecond)
		leaseA.Release()
	}()
	leaseB, err := s.Acquire(context.Background(), b)
	if err != nil {
		t.Fatalf("queued acquire b: %v", err)
	}
	leaseB.Release()
	if launcher.callCount() != 2 {
		t.Fatalf("launcher calls = %d", launcher.callCount())
	}
}

func TestSchedulerQueueFull(t *testing.T) {
	s := NewScheduler(nil, SchedulerOptions{QueueMax: 1})
	s.mu.Lock()
	if _, err := s.enqueueLocked("a"); err != nil {
		s.mu.Unlock()
		t.Fatal(err)
	}
	_, err := s.enqueueLocked("b")
	s.mu.Unlock()
	var pe *PlacementError
	if !errors.As(err, &pe) || pe.Code != "queue_full" {
		t.Fatalf("error = %v", err)
	}
	s.leaveQueue("a")
}

func TestSchedulerNoCompatibleRuntime(t *testing.T) {
	launcher := &recordingLauncher{}
	refStr := "demo:1"
	m := placementManifest(t, []string{"sm86-cu124-linux-x86_64-py312"}, nil)
	s := newTestScheduler(t, launcher, map[string]*manifest.Manifest{refStr: m}, twoGPUInventory(28<<30), SchedulerOptions{})
	_, err := s.Acquire(context.Background(), refStr)
	var pe *PlacementError
	if !errors.As(err, &pe) || pe.Code != "no_placement" || pe.Reason != reasonNoCompatibleRuntime {
		t.Fatalf("error = %v", err)
	}
	if launcher.callCount() != 0 {
		t.Fatalf("launcher calls = %d", launcher.callCount())
	}
}

func TestSchedulerCPUFallbackDoesNotPinCUDA(t *testing.T) {
	launcher := &recordingLauncher{}
	refStr := "demo:1"
	m := placementManifest(t, []string{"cpu-linux-x86_64-py312"}, nil)
	s := newTestScheduler(t, launcher, map[string]*manifest.Manifest{refStr: m}, twoGPUInventory(28<<30), SchedulerOptions{})
	lease, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatal(err)
	}
	lease.Release()
	if env := launcher.env(refStr); len(env) != 0 {
		t.Fatalf("CPU placement set env: %v", env)
	}
}

func TestSchedulerIdleStopAndRestart(t *testing.T) {
	launcher := &recordingLauncher{}
	refStr := "demo:1"
	s := newTestScheduler(t, launcher,
		map[string]*manifest.Manifest{refStr: gpuManifest(t)},
		twoGPUInventory(28<<30),
		SchedulerOptions{IdleStopSeconds: 1})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	s.Start(ctx)

	lease, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatal(err)
	}
	lease.Release()

	deadline := time.Now().Add(4 * time.Second)
	for s.Resident(refStr) {
		if time.Now().After(deadline) {
			t.Fatal("idle resident was not stopped")
		}
		time.Sleep(100 * time.Millisecond)
	}
	lease, err = s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatalf("restart after idle stop: %v", err)
	}
	lease.Release()
	if launcher.callCount() != 2 {
		t.Fatalf("launcher calls = %d", launcher.callCount())
	}
}

func TestSchedulerReconcilesCrashedResident(t *testing.T) {
	launcher := &recordingLauncher{}
	refStr := "demo:1"
	s := newTestScheduler(t, launcher,
		map[string]*manifest.Manifest{refStr: gpuManifest(t)},
		twoGPUInventory(28<<30),
		SchedulerOptions{})
	lease, err := s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatal(err)
	}
	lease.Release()

	launcher.process(refStr).Stop(context.Background())
	if s.Resident(refStr) {
		t.Fatal("crashed resident should be reconciled away")
	}
	lease, err = s.Acquire(context.Background(), refStr)
	if err != nil {
		t.Fatalf("restart after crash: %v", err)
	}
	lease.Release()
	if launcher.callCount() != 2 {
		t.Fatalf("launcher calls = %d", launcher.callCount())
	}
}

func TestSchedulerStartFailureIsNotRetriedInALoop(t *testing.T) {
	launcher := &recordingLauncher{err: errors.New("oom")}
	refStr := "demo:1"
	s := newTestScheduler(t, launcher,
		map[string]*manifest.Manifest{refStr: gpuManifest(t)},
		twoGPUInventory(28<<30),
		SchedulerOptions{})
	if _, err := s.Acquire(context.Background(), refStr); err == nil {
		t.Fatal("expected start failure")
	}
	if launcher.callCount() != 1 {
		t.Fatalf("launcher calls = %d, want 1", launcher.callCount())
	}
	if s.Resident(refStr) {
		t.Fatal("failed start must not leave resident state")
	}
}
