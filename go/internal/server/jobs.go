package server

import (
	"context"
	"fmt"
	"sync"
	"time"
)

// Event is one job progress event.
type Event struct {
	Time    string `json:"time"`
	Phase   string `json:"phase"`
	Message string `json:"message,omitempty"`
}

// Job is a local pull or load job.
type Job struct {
	ID     string  `json:"id"`
	Type   string  `json:"type"`
	Ref    string  `json:"ref"`
	State  string  `json:"state"`
	Error  string  `json:"error,omitempty"`
	Events []Event `json:"events"`

	mu      sync.Mutex
	done    chan struct{}
	subs    map[chan Event]struct{}
	closed  bool
	onEvent func(state string, ev Event)
}

func (j *Job) emit(phase, message string) {
	j.mu.Lock()
	ev := Event{Time: time.Now().UTC().Format(time.RFC3339Nano), Phase: phase, Message: message}
	j.Events = append(j.Events, ev)
	for ch := range j.subs {
		select {
		case ch <- ev:
		default:
		}
	}
	state := j.State
	j.mu.Unlock()
	if j.onEvent != nil {
		j.onEvent(state, ev)
	}
}

func (j *Job) finish(err error) {
	j.mu.Lock()
	if j.closed {
		j.mu.Unlock()
		return
	}
	j.closed = true
	ev := Event{Time: time.Now().UTC().Format(time.RFC3339Nano), Phase: "done"}
	if err != nil {
		j.State = "failed"
		j.Error = err.Error()
		ev.Phase = "failed"
		ev.Message = err.Error()
	} else {
		j.State = "done"
	}
	state := j.State
	j.Events = append(j.Events, ev)
	close(j.done)
	for ch := range j.subs {
		close(ch)
	}
	j.subs = nil
	j.mu.Unlock()
	if j.onEvent != nil {
		j.onEvent(state, ev)
	}
}

func (j *Job) subscribe() ([]Event, <-chan Event, <-chan struct{}) {
	ch := make(chan Event, 32)
	j.mu.Lock()
	history := append([]Event(nil), j.Events...)
	if j.closed {
		close(ch)
	} else {
		j.subs[ch] = struct{}{}
	}
	j.mu.Unlock()
	return history, ch, j.done
}

// JobUpdate is broadcast for WebSocket clients.
type JobUpdate struct {
	ID    string `json:"id"`
	Type  string `json:"type"`
	Ref   string `json:"ref"`
	State string `json:"state"`
	Event Event  `json:"event"`
}

// JobManager owns local asynchronous jobs.
type JobManager struct {
	mu   sync.Mutex
	seq  int
	jobs map[string]*Job
	subs map[chan JobUpdate]struct{}
}

func NewJobManager() *JobManager {
	return &JobManager{jobs: map[string]*Job{}, subs: map[chan JobUpdate]struct{}{}}
}

// Subscribe returns a channel of all job updates plus an unsubscribe func.
func (m *JobManager) Subscribe() (<-chan JobUpdate, func()) {
	ch := make(chan JobUpdate, 128)
	m.mu.Lock()
	m.subs[ch] = struct{}{}
	m.mu.Unlock()
	return ch, func() {
		m.mu.Lock()
		if _, ok := m.subs[ch]; ok {
			delete(m.subs, ch)
			close(ch)
		}
		m.mu.Unlock()
	}
}

func (m *JobManager) publish(u JobUpdate) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for ch := range m.subs {
		select {
		case ch <- u:
		default:
		}
	}
}

func (m *JobManager) Start(ctx context.Context, typ, ref string, run func(context.Context, func(string, string)) error) *Job {
	m.mu.Lock()
	m.seq++
	j := &Job{
		ID:    fmt.Sprintf("%s-%d", typ, m.seq),
		Type:  typ,
		Ref:   ref,
		State: "running",
		done:  make(chan struct{}),
		subs:  map[chan Event]struct{}{},
	}
	j.onEvent = func(state string, ev Event) {
		m.publish(JobUpdate{ID: j.ID, Type: j.Type, Ref: j.Ref, State: state, Event: ev})
	}
	m.jobs[j.ID] = j
	m.mu.Unlock()

	go func() {
		err := run(ctx, j.emit)
		j.finish(err)
	}()
	return j
}

func (m *JobManager) Get(id string) (*Job, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	j, ok := m.jobs[id]
	return j, ok
}
