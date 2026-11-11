package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func TestSmokeModelValidation(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	s := &Server{}
	for _, tc := range []struct {
		name string
		body string
		code int
	}{
		{"missing-ref", `{}`, http.StatusBadRequest},
		{"not-cached", `{"ref":"demo:1"}`, http.StatusNotFound},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/v1/models/smoke", strings.NewReader(tc.body))
			s.Handler().ServeHTTP(rec, req)
			if rec.Code != tc.code {
				t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
			}
		})
	}
}

func TestSmokeRunCapturesLog(t *testing.T) {
	bin, err := exec.LookPath("true")
	if err != nil {
		t.Skip("true binary not available")
	}
	dir := t.TempDir()
	logPath := filepath.Join(dir, "demo.smoke.log")
	s := &Server{FlashcliBin: bin}
	var mu sync.Mutex
	lines := []string{}
	emit := func(_, msg string) {
		mu.Lock()
		lines = append(lines, msg)
		mu.Unlock()
	}
	if err := s.smokeRun(context.Background(), "demo:1", logPath, emit); err != nil {
		t.Fatal(err)
	}
	blob, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(blob), "$ "+bin+" run demo:1") || !strings.Contains(string(blob), "exit=<nil>") {
		t.Fatalf("log file = %q", blob)
	}
}

func TestSmokeServeRequest(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/models":
			_ = json.NewEncoder(w).Encode(map[string]any{"data": []map[string]string{{"id": "demo-model"}}})
		case "/v1/chat/completions":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"choices": []map[string]any{{"message": map[string]string{"content": "pong"}}},
			})
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	logPath := filepath.Join(t.TempDir(), "serve.smoke.log")
	s := &Server{}
	lines := []string{}
	emit := func(_, msg string) { lines = append(lines, msg) }
	if err := s.smokeServeRequest(context.Background(), "demo:1", srv.URL, logPath, emit); err != nil {
		t.Fatal(err)
	}
	blob, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatal(err)
	}
	logText := string(blob)
	if !strings.Contains(logText, "model=demo-model") || !strings.Contains(logText, "pong") {
		t.Fatalf("unexpected log: %s", logText)
	}
	if !strings.Contains(strings.Join(lines, "\n"), "status=200") {
		t.Fatalf("missing status progress: %v", lines)
	}
}

func TestJobCancel(t *testing.T) {
	jm := NewJobManager()
	started := make(chan struct{})
	job := jm.Start(context.Background(), "smoke", "demo:1", func(ctx context.Context, emit func(string, string)) error {
		close(started)
		<-ctx.Done()
		return ctx.Err()
	})
	<-started
	if !job.Cancel() {
		t.Fatal("Cancel returned false")
	}
	<-job.done
	job.mu.Lock()
	state := job.State
	job.mu.Unlock()
	if state != "failed" {
		t.Fatalf("state = %q, want failed", state)
	}
}
