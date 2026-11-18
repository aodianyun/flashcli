package server

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func TestServerLogPersistsAcrossRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "flashserver.log")
	InitLogFile(path)
	defer InitLogFile("")
	fmt.Fprintln(LogSink(), "api POST /v1/apps/xym/demo/start -> 202 (1ms, 10B)")
	fmt.Fprintln(LogSink(), "setup workbuddy: done")

	// Simulate the next daemon process: re-init from the same file.
	InitLogFile(path)
	text := strings.Join(serverLogLines(20), "\n")
	if !strings.Contains(text, "POST /v1/apps/xym/demo/start") {
		t.Fatalf("api line lost: %q", text)
	}
	if !strings.Contains(text, "setup workbuddy: done") {
		t.Fatalf("setup line lost: %q", text)
	}
}

func TestRequestLogRedactsSecrets(t *testing.T) {
	InitLogFile("")
	defer InitLogFile("")
	s := &Server{Source: fakeSource{}}
	req := httptest.NewRequest(http.MethodPost, "/v1/models/load",
		strings.NewReader(`{"ref":"demo:1","api_key":"super-secret"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)

	text := strings.Join(serverLogLines(20), "\n")
	if !strings.Contains(text, "api POST /v1/models/load") {
		t.Fatalf("request not logged: %q", text)
	}
	if strings.Contains(text, "super-secret") {
		t.Fatalf("secret leaked into the log: %q", text)
	}
	if !strings.Contains(text, "***") {
		t.Fatalf("redaction marker missing: %q", text)
	}
}
