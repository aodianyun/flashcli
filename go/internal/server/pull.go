package server

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/aodianyun/flashcli/go/internal/host"
)

// Puller performs a bundle pull. It is an interface for tests and future
// remote/agent implementations.
type Puller interface {
	Pull(context.Context, string, host.PullOptions) (host.PullResult, error)
}

type hostPuller struct{}

func (hostPuller) Pull(ctx context.Context, ref string, opts host.PullOptions) (host.PullResult, error) {
	return host.Pull(ctx, ref, opts)
}

type pullRequest struct {
	Ref string `json:"ref"`
}

func (s *Server) pull(w http.ResponseWriter, r *http.Request) {
	if s.Puller == nil {
		writeError(w, http.StatusNotImplemented, context.Canceled)
		return
	}
	var req pullRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Ref == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	job := s.Jobs.Start(context.Background(), "pull", req.Ref, func(ctx context.Context, emit func(string, string)) error {
		_, err := s.Puller.Pull(ctx, req.Ref, host.PullOptions{Progress: func(ev host.PullEvent) {
			emit(ev.Phase, ev.Message)
		}})
		return err
	})
	writeJSON(w, http.StatusAccepted, map[string]any{"job_id": job.ID, "state": job.State})
}

func (s *Server) job(w http.ResponseWriter, r *http.Request) {
	j, ok := s.Jobs.Get(r.PathValue("id"))
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "job not found"})
		return
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	writeJSON(w, http.StatusOK, j)
}

func (s *Server) jobEvents(w http.ResponseWriter, r *http.Request) {
	j, ok := s.Jobs.Get(r.PathValue("id"))
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "job not found"})
		return
	}
	history, ch, done := j.subscribe()
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, http.ErrNotSupported)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(http.StatusOK)
	enc := json.NewEncoder(w)
	for _, ev := range history {
		_, _ = w.Write([]byte("event: progress\n"))
		_ = enc.Encode(ev)
		_, _ = w.Write([]byte("\n"))
	}
	flusher.Flush()
	for {
		select {
		case ev, open := <-ch:
			if !open {
				_, _ = w.Write([]byte("event: done\n"))
				_, _ = w.Write([]byte("data: {}\n\n"))
				flusher.Flush()
				return
			}
			_, _ = w.Write([]byte("event: progress\n"))
			_ = enc.Encode(ev)
			_, _ = w.Write([]byte("\n"))
			flusher.Flush()
		case <-done:
			// drain channel until closed; done is closed at the same time
			for ev := range ch {
				_, _ = w.Write([]byte("event: progress\n"))
				_ = enc.Encode(ev)
				_, _ = w.Write([]byte("\n"))
			}
			_, _ = w.Write([]byte("event: done\n"))
			_, _ = w.Write([]byte("data: {}\n\n"))
			flusher.Flush()
			return
		case <-r.Context().Done():
			return
		}
	}
}
