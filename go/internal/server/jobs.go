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

// Job is a local pull job.
type Job struct {
	ID     string  `json:"id"`
	Type   string  `json:"type"`
	Ref    string  `json:"ref"`
	State  string  `json:"state"`
	Error  string  `json:"error,omitempty"`
	Events []Event `json:"events"`

	mu     sync.Mutex
	done   chan struct{}
	subs   map[chan Event]struct{}
	closed bool
}

func (j *Job) emit(phase, message string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	ev := Event{Time: time.Now().UTC().Format(time.RFC3339Nano), Phase: phase, Message: message}
	j.Events = append(j.Events, ev)
	for ch := range j.subs {
		select {
		case ch <- ev:
		default:
		}
	}
}

func (j *Job) finish(err error) {
	j.mu.Lock()
	defer j.mu.Unlock()
	if j.closed {
		return
	}
	j.closed = true
	if err != nil {
		j.State = "failed"
		j.Error = err.Error()
	} else {
		j.State = "done"
	}
	close(j.done)
	for ch := range j.subs {
		close(ch)
	}
	j.subs = nil
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

// JobManager owns local asynchronous jobs.
type JobManager struct {
	mu   sync.Mutex
	seq  int
	jobs map[string]*Job
}

func NewJobManager() *JobManager { return &JobManager{jobs: map[string]*Job{}} }

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
