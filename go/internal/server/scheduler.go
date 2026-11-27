package server

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

// Resident lifecycle states (independent of disk preload state).
const (
	residentStopped  = "stopped"
	residentStarting = "starting"
	residentReady    = "ready"
	residentBusy     = "busy"
	residentStopping = "stopping"
)

var errNeedEviction = errors.New("eviction needed")

// PlacementError is an OpenAI-shaped scheduling failure for the gateway.
type PlacementError struct {
	Code   string `json:"code"`
	Reason string `json:"reason,omitempty"`
	Ref    string `json:"model,omitempty"`
}

func (e *PlacementError) Error() string {
	if e.Reason != "" {
		return fmt.Sprintf("%s: %s", e.Code, e.Reason)
	}
	return e.Code
}

// SchedulerOptions configures demand-driven resident lifecycle management.
type SchedulerOptions struct {
	MaxLoaded           int
	VRAMHeadroomMiB     int64
	IdleStopSeconds     int
	QueueTimeoutSeconds int
	QueueMax            int
	CPUDisabled         bool
	Inventory           func(context.Context) DeviceInventory
	Inspect             func(string) (BundleInfo, error)
	Notify              func(event string, data map[string]any)
}

// ResidentInfo is the scheduler's public view of one ref.
type ResidentInfo struct {
	Ref            string    `json:"ref"`
	State          string    `json:"state"`
	Devices        []string  `json:"devices,omitempty"`
	ActiveRequests int       `json:"active_requests"`
	StartedAt      time.Time `json:"started_at,omitempty"`
	LastUsed       time.Time `json:"last_used,omitempty"`
}

// SchedulerSnapshot is used by /api/v1/scheduler.
type SchedulerSnapshot struct {
	Reservations []ResidentInfo `json:"reservations"`
	Queue        []string       `json:"queue"`
	ActiveLeases int            `json:"active_leases"`
	Waiters      int            `json:"waiters"`
}

type resident struct {
	ref       string
	state     string
	devices   []string
	vramMiB   int64
	startedAt time.Time
	lastUsed  time.Time
	leases    int
}

type startCall struct {
	done   chan struct{}
	err    error
	cancel context.CancelFunc
}

type placementPlan struct {
	Devices []string
	// VRAMMiB is the per-GPU reservation used while the process is starting.
	// Once ready, the live device inventory reflects the actual usage.
	VRAMMiB int64
	Env     []string
}

// Scheduler owns demand-driven resident start/stop, leases, idle stop, eviction
// and the bounded queue. It wraps Manager for the actual serve process.
type Scheduler struct {
	mu        sync.Mutex
	manager   *Manager
	opts      SchedulerOptions
	residents map[string]*resident
	starting  map[string]*startCall
	stopping  map[string]*startCall
	waiting   map[string]int
	waiters   int
	notify    chan struct{}
}

func NewScheduler(manager *Manager, opts SchedulerOptions) *Scheduler {
	if opts.Inventory == nil {
		opts.Inventory = func(context.Context) DeviceInventory { return inventoryFrom(nil, "") }
	}
	if opts.Inspect == nil {
		opts.Inspect = inspectBundle
	}
	if opts.IdleStopSeconds < 0 {
		opts.IdleStopSeconds = 0
	}
	if opts.IdleStopSeconds == 0 {
		opts.IdleStopSeconds = 600
	}
	if opts.VRAMHeadroomMiB < 0 {
		opts.VRAMHeadroomMiB = 0
	}
	return &Scheduler{
		manager:   manager,
		opts:      opts,
		residents: map[string]*resident{},
		starting:  map[string]*startCall{},
		stopping:  map[string]*startCall{},
		waiting:   map[string]int{},
		notify:    make(chan struct{}),
	}
}

// Start runs the idle reaper until ctx is cancelled.
func (s *Scheduler) Start(ctx context.Context) {
	go func() {
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				s.reap()
			}
		}
	}()
}

// Lease is one active inference request holding a resident model.
type Lease struct {
	Ref   string
	sched *Scheduler
	// res identifies the resident generation this lease was taken on. A crash
	// and restart replaces the resident, so a stale lease must not decrement the
	// new generation's count.
	res  *resident
	once sync.Once
}

// Release drops the lease. It is idempotent.
func (l *Lease) Release() {
	if l == nil || l.sched == nil {
		return
	}
	l.once.Do(func() { l.sched.release(l.Ref, l.res) })
}

// Acquire ensures a resident and takes one lease. It waits for an in-flight
// start, evicts idle residents when needed, and queues while placement is busy.
func (s *Scheduler) Acquire(ctx context.Context, refStr string) (*Lease, error) {
	if s.manager == nil {
		return nil, errors.New("scheduler has no model manager")
	}
	deadline := time.Now().Add(time.Duration(s.opts.QueueTimeoutSeconds) * time.Second)
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		// Inspect and probe outside the scheduler lock: both can touch the
		// network or block on device telemetry.
		info, err := s.opts.Inspect(refStr)
		if err != nil {
			return nil, err
		}
		inv := s.opts.Inventory(ctx)

		s.mu.Lock()
		s.reconcileLocked()
		if r := s.residents[refStr]; r != nil {
			switch r.state {
			case residentReady, residentBusy:
				r.leases++
				r.state = residentBusy
				r.lastUsed = time.Now().UTC()
				s.mu.Unlock()
				return &Lease{Ref: refStr, sched: s, res: r}, nil
			case residentStarting, residentStopping:
				calls := s.starting
				if r.state == residentStopping {
					calls = s.stopping
				}
				call := calls[refStr]
				s.mu.Unlock()
				if call == nil {
					continue
				}
				select {
				case <-call.done:
					if call.err != nil {
						return nil, call.err
					}
					continue
				case <-ctx.Done():
					return nil, ctx.Err()
				}
			}
		}

		plan, err := s.planLocked(refStr, info, inv)
		if errors.Is(err, errNeedEviction) {
			s.mu.Unlock()
			if !s.evictIdle(refStr) {
				time.Sleep(50 * time.Millisecond)
			} else {
				// Give the driver a moment to release VRAM.
				time.Sleep(300 * time.Millisecond)
			}
			continue
		}
		if err != nil {
			var pe *PlacementError
			// Only a temporary resource shortage can be resolved by waiting.
			// No runtime compatibility is permanent, so fail immediately.
			canQueue := errors.As(err, &pe) && pe.Reason == reasonResourceExhausted &&
				s.hasActiveLocked() && s.opts.QueueTimeoutSeconds > 0
			if !canQueue {
				s.mu.Unlock()
				return nil, err
			}
			notify, qerr := s.enqueueLocked(refStr)
			s.mu.Unlock()
			if qerr != nil {
				return nil, qerr
			}
			wait := time.Until(deadline)
			if wait <= 0 {
				s.leaveQueue(refStr)
				return nil, pe
			}
			timer := time.NewTimer(wait)
			select {
			case <-notify:
				timer.Stop()
			case <-timer.C:
				s.leaveQueue(refStr)
				return nil, pe
			case <-ctx.Done():
				timer.Stop()
				s.leaveQueue(refStr)
				return nil, ctx.Err()
			}
			s.leaveQueue(refStr)
			continue
		}

		startCtx, cancel := context.WithCancel(context.Background())
		call := &startCall{done: make(chan struct{}), cancel: cancel}
		s.starting[refStr] = call
		s.residents[refStr] = &resident{
			ref: refStr, state: residentStarting, devices: plan.Devices, vramMiB: plan.VRAMMiB,
			startedAt: time.Now().UTC(), lastUsed: time.Now().UTC(),
		}
		s.mu.Unlock()

		// Start in the background so the caller's deadline returns
		// model_starting while the resident continues to load.
		go s.startResident(startCtx, refStr, plan, call)
		select {
		case <-call.done:
			if call.err != nil {
				return nil, call.err
			}
			continue
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
}

// startResident performs the actual serve start and publishes the result. It
// runs with a background context so a client deadline does not cancel it.
func (s *Scheduler) startResident(ctx context.Context, refStr string, plan placementPlan, call *startCall) {
	if call.cancel != nil {
		defer call.cancel()
	}
	_, startErr := s.manager.LoadScheduled(ctx, refStr, plan.Env)

	s.mu.Lock()
	delete(s.starting, refStr)
	call.err = startErr
	stopCall := s.stopping[refStr]
	if startErr != nil {
		delete(s.residents, refStr)
		if stopCall != nil {
			delete(s.stopping, refStr)
		}
		s.broadcastLocked()
		s.mu.Unlock()
		close(call.done)
		if stopCall != nil {
			close(stopCall.done)
		}
		s.emit("resident_start_failed", map[string]any{"ref": refStr, "error": startErr.Error()})
		return
	}
	if stopCall != nil {
		// A force stop raced the start. Stop the freshly started process and
		// wake both the start waiter and the stop waiter instead of leaving an
		// orphan resident behind.
		delete(s.stopping, refStr)
		delete(s.residents, refStr)
		s.broadcastLocked()
		s.mu.Unlock()
		_ = s.manager.Unload(context.Background(), refStr)
		call.err = errors.New("model was stopped during start")
		close(call.done)
		close(stopCall.done)
		s.emit("resident_stopped", map[string]any{"ref": refStr})
		return
	}
	r := s.residents[refStr]
	if r == nil {
		r = &resident{ref: refStr}
		s.residents[refStr] = r
	}
	r.state = residentReady
	r.devices = plan.Devices
	r.vramMiB = plan.VRAMMiB
	r.lastUsed = time.Now().UTC()
	s.broadcastLocked()
	s.mu.Unlock()
	close(call.done)
	s.emit("resident_started", map[string]any{"ref": refStr, "devices": plan.Devices})
}

// reservedInventoryLocked subtracts VRAM reservations for residents that are
// still starting. Ready residents are already visible in the live inventory, so
// subtracting them again would double count. The caller holds s.mu.
func (s *Scheduler) reservedInventoryLocked(inv DeviceInventory) DeviceInventory {
	reserved := map[string]int64{}
	for _, r := range s.residents {
		if r.state != residentStarting || r.vramMiB <= 0 {
			continue
		}
		for _, id := range r.devices {
			reserved[id] += r.vramMiB
		}
	}
	if len(reserved) == 0 {
		return inv
	}
	devices := make([]DeviceInfo, len(inv.Devices))
	copy(devices, inv.Devices)
	for i := range devices {
		if add := reserved[devices[i].ID]; add > 0 {
			devices[i].MemoryFreeBytes -= add * 1024 * 1024
			if devices[i].MemoryFreeBytes < 0 {
				devices[i].MemoryFreeBytes = 0
			}
		}
	}
	inv.Devices = devices
	return inv
}

// planLocked answers whether ref can start now. The caller holds s.mu.
func (s *Scheduler) planLocked(refStr string, info BundleInfo, inv DeviceInventory) (placementPlan, error) {
	active := s.activeCountLocked()
	if s.manager != nil {
		if used, _ := s.manager.Slots(); used > active {
			active = used
		}
	}
	if s.opts.MaxLoaded > 0 && active >= s.opts.MaxLoaded {
		if s.hasIdleLocked() {
			return placementPlan{}, errNeedEviction
		}
		return placementPlan{}, &PlacementError{Code: "no_placement", Reason: reasonResourceExhausted, Ref: refStr}
	}
	if info.Manifest == nil {
		// No manifest metadata (test doubles / legacy): let the process start
		// without a device constraint rather than inventing placement.
		return placementPlan{}, nil
	}
	effInv := s.reservedInventoryLocked(inv)
	req := placementFor(refStr, info.Manifest, effInv, effInv.CUDATag, s.opts.VRAMHeadroomMiB)
	applyCPUPolicy(&req, s.opts.CPUDisabled)
	if len(req.GPUs) == 0 && !req.CPUAdmitted {
		if s.hasIdleLocked() {
			return placementPlan{}, errNeedEviction
		}
		return placementPlan{}, &PlacementError{Code: "no_placement", Reason: req.Reason, Ref: refStr}
	}
	plan := placementPlan{Devices: req.GPUs}
	if len(req.GPUs) > 0 {
		plan.Env = append(plan.Env, "CUDA_VISIBLE_DEVICES="+strings.Join(req.GPUs, ","))
		plan.VRAMMiB = vramNeedMiB(info.Manifest.Resources().MinVRAMMiB, s.opts.VRAMHeadroomMiB)
	}
	return plan, nil
}

func (s *Scheduler) activeCountLocked() int {
	n := 0
	for _, r := range s.residents {
		if r.state == residentStarting || r.state == residentReady || r.state == residentBusy {
			n++
		}
	}
	return n
}

func (s *Scheduler) hasActiveLocked() bool {
	for _, r := range s.residents {
		if r.state == residentStarting || r.state == residentBusy {
			return true
		}
	}
	return false
}

func (s *Scheduler) hasIdleLocked() bool {
	for _, r := range s.residents {
		if r.leases == 0 && r.state == residentReady {
			return true
		}
	}
	return false
}

// lruIdleLocked returns the least-recently-used idle resident, excluding ref.
func (s *Scheduler) lruIdleLocked(exclude string) (string, bool) {
	best := ""
	var bestTime time.Time
	for ref, r := range s.residents {
		if ref == exclude || r.leases != 0 || r.state != residentReady {
			continue
		}
		if best == "" || r.lastUsed.Before(bestTime) {
			best, bestTime = ref, r.lastUsed
		}
	}
	return best, best != ""
}

// evictIdle stops one idle resident (LRU) and reports whether it did.
func (s *Scheduler) evictIdle(exclude string) bool {
	s.mu.Lock()
	ref, ok := s.lruIdleLocked(exclude)
	s.mu.Unlock()
	if !ok {
		return false
	}
	s.stopResident(ref)
	return true
}

// stopResident stops one scheduler-owned resident. It is a no-op when the
// resident has active leases.
func (s *Scheduler) stopResident(refStr string) {
	s.mu.Lock()
	r := s.residents[refStr]
	if r == nil || r.leases > 0 || r.state == residentStopping {
		s.mu.Unlock()
		return
	}
	wasStarting := r.state == residentStarting
	startingCall := s.starting[refStr]
	call := &startCall{done: make(chan struct{})}
	r.state = residentStopping
	s.stopping[refStr] = call
	s.broadcastLocked()
	s.mu.Unlock()

	if wasStarting {
		// Cancel the in-flight load, then wait for startResident to unload the
		// freshly created process. Waiting here keeps unload from deleting assets
		// while the child is still loading them.
		if startingCall != nil && startingCall.cancel != nil {
			startingCall.cancel()
		}
		<-call.done
		return
	}

	if s.manager != nil {
		_ = s.manager.Unload(context.Background(), refStr)
	}

	s.mu.Lock()
	delete(s.residents, refStr)
	delete(s.stopping, refStr)
	s.broadcastLocked()
	s.mu.Unlock()
	close(call.done)
	s.emit("resident_stopped", map[string]any{"ref": refStr})
}

// release ends one lease. A lease from a resident generation that was
// reconciled away (crash/OOM) or stopped must not affect its replacement.
func (s *Scheduler) release(refStr string, res *resident) {
	s.mu.Lock()
	if r := s.residents[refStr]; r != nil && r == res {
		if r.leases > 0 {
			r.leases--
		}
		if r.leases == 0 && r.state == residentBusy {
			r.state = residentReady
		}
		r.lastUsed = time.Now().UTC()
	}
	s.broadcastLocked()
	s.mu.Unlock()
}

// Stop stops a resident (used by force unload). Active requests lose their
// lease; the gateway must treat them as cancelled.
func (s *Scheduler) Stop(ctx context.Context, refStr string) error {
	s.mu.Lock()
	if r := s.residents[refStr]; r != nil {
		r.leases = 0
	}
	s.mu.Unlock()
	s.stopResident(refStr)
	if s.manager != nil {
		return s.manager.Unload(ctx, refStr)
	}
	return nil
}

// Busy reports whether ref is resident or starting/stopping. A ready resident
// with no leases is still "resident" for unload purposes.
func (s *Scheduler) Busy(refStr string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.reconcileLocked()
	r := s.residents[refStr]
	return r != nil
}

// ActiveRequests reports the current lease count.
func (s *Scheduler) ActiveRequests(refStr string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	if r := s.residents[refStr]; r != nil {
		return r.leases
	}
	return 0
}

// Resident reports whether the scheduler owns a resident for ref.
func (s *Scheduler) Resident(refStr string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.reconcileLocked()
	_, ok := s.residents[refStr]
	return ok
}

// Drained reports whether ref has no active leases and is not starting/stopping.
func (s *Scheduler) Drained(refStr string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	r := s.residents[refStr]
	if r == nil {
		return true
	}
	return r.leases == 0 && r.state != residentStarting && r.state != residentStopping
}

// States returns the current resident view.
func (s *Scheduler) States() map[string]ResidentInfo {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.reconcileLocked()
	out := make(map[string]ResidentInfo, len(s.residents))
	for ref, r := range s.residents {
		out[ref] = ResidentInfo{
			Ref: ref, State: r.state, Devices: append([]string(nil), r.devices...),
			ActiveRequests: r.leases, StartedAt: r.startedAt, LastUsed: r.lastUsed,
		}
	}
	return out
}

// Snapshot returns reservations and queued refs for /api/v1/scheduler.
func (s *Scheduler) Snapshot() SchedulerSnapshot {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.reconcileLocked()
	out := SchedulerSnapshot{
		Reservations: make([]ResidentInfo, 0, len(s.residents)),
		Queue:        []string{},
	}
	for ref, r := range s.residents {
		out.Reservations = append(out.Reservations, ResidentInfo{
			Ref: ref, State: r.state, Devices: append([]string(nil), r.devices...),
			ActiveRequests: r.leases, StartedAt: r.startedAt, LastUsed: r.lastUsed,
		})
		out.ActiveLeases += r.leases
	}
	out.Waiters = s.waiters
	sort.Slice(out.Reservations, func(i, j int) bool { return out.Reservations[i].Ref < out.Reservations[j].Ref })
	for ref, n := range s.waiting {
		if n > 0 {
			out.Queue = append(out.Queue, ref)
		}
	}
	sort.Strings(out.Queue)
	return out
}

// reconcileLocked drops state for processes that died outside the scheduler
// (crash, OOM kill), so the next request starts once instead of reusing a dead
// endpoint.
func (s *Scheduler) reconcileLocked() {
	if s.manager == nil {
		return
	}
	for ref, r := range s.residents {
		if r.state != residentReady && r.state != residentBusy {
			continue
		}
		if s.manager.IsRunning(ref) {
			continue
		}
		delete(s.residents, ref)
		s.broadcastLocked()
	}
}

func (s *Scheduler) enqueueLocked(refStr string) (<-chan struct{}, error) {
	if s.opts.QueueMax > 0 && s.waiters >= s.opts.QueueMax {
		return nil, &PlacementError{Code: "queue_full", Reason: "queue_full", Ref: refStr}
	}
	s.waiters++
	s.waiting[refStr]++
	return s.notify, nil
}

func (s *Scheduler) leaveQueue(refStr string) {
	s.mu.Lock()
	if s.waiters > 0 {
		s.waiters--
	}
	if n := s.waiting[refStr]; n > 1 {
		s.waiting[refStr] = n - 1
	} else {
		delete(s.waiting, refStr)
	}
	s.mu.Unlock()
}

func (s *Scheduler) broadcastLocked() {
	close(s.notify)
	s.notify = make(chan struct{})
}

func (s *Scheduler) emit(event string, data map[string]any) {
	if s.opts.Notify != nil {
		s.opts.Notify(event, data)
	}
}

// reap stops idle residents after idle_stop_seconds.
func (s *Scheduler) reap() {
	idle := s.opts.IdleStopSeconds
	if idle <= 0 {
		return
	}
	cutoff := time.Now().Add(-time.Duration(idle) * time.Second)
	s.mu.Lock()
	s.reconcileLocked()
	var refs []string
	for ref, r := range s.residents {
		if r.leases == 0 && r.state == residentReady && !r.lastUsed.IsZero() && r.lastUsed.Before(cutoff) {
			refs = append(refs, ref)
		}
	}
	s.mu.Unlock()
	for _, ref := range refs {
		s.stopResident(ref)
	}
}
