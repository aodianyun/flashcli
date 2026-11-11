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
	res := s.smokeRun(context.Background(), "demo:1", logPath)
	if !res.OK {
		t.Fatalf("smoke run failed: %s", res.Log)
	}
	if !strings.Contains(res.Log, "$ "+bin+" run demo:1") {
		t.Fatalf("missing command in log: %s", res.Log)
	}
	blob, err := os.ReadFile(logPath)
	if err != nil || !strings.Contains(string(blob), "exit=<nil>") {
		t.Fatalf("log file = %q, err=%v", blob, err)
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
	res := s.smokeServeRequest(context.Background(), "demo:1", srv.URL, logPath)
	if !res.OK || res.Status != http.StatusOK {
		t.Fatalf("smoke serve failed: %+v", res)
	}
	if !strings.Contains(res.Log, "model=demo-model") || !strings.Contains(res.Log, "pong") {
		t.Fatalf("unexpected log: %s", res.Log)
	}
}
