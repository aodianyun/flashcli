package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/gpu"
)

func TestTailFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "model.log")
	blob := "one\ntwo\nthree\nfour\n"
	if err := os.WriteFile(path, []byte(blob), 0o644); err != nil {
		t.Fatal(err)
	}
	lines, err := tailFile(path, 2)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(lines, ","); got != "three,four" {
		t.Fatalf("lines = %q", got)
	}
}

func TestServeLogName(t *testing.T) {
	got := serveLogName("flashcli-bundle/qwen3:1.0.0")
	want := "flashcli-bundle_qwen3_1.0.0.log"
	if got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestServerLogRing(t *testing.T) {
	logRingMu.Lock()
	logRing = nil
	logRingMu.Unlock()
	w := LogSink()
	for _, line := range []string{"a", "b", "c"} {
		if _, err := w.Write([]byte(line + "\n")); err != nil {
			t.Fatal(err)
		}
	}
	lines := serverLogLines(2)
	if got := strings.Join(lines, ","); got != "b,c" {
		t.Fatalf("lines = %q", got)
	}
}

func TestOpenAPISpecInSync(t *testing.T) {
	doc, err := os.ReadFile(filepath.Join("..", "..", "..", "docs", "openapi.yaml"))
	if err != nil {
		t.Fatalf("read docs/openapi.yaml: %v", err)
	}
	if string(doc) != string(openapiDoc) {
		t.Fatal("docs/openapi.yaml and go/internal/server/openapi.yaml differ; copy the docs file into the server package")
	}
}

func TestGpuHistorySamples(t *testing.T) {
	util := 37
	s := &Server{GPU: func(context.Context) ([]gpu.Device, error) {
		return []gpu.Device{{Index: 0, MemoryUsed: 1024, UtilizationGPU: &util}}, nil
	}}
	s.sampleGPUHistory(context.Background())
	s.sampleGPUHistory(context.Background())
	req := httptest.NewRequest(http.MethodGet, "/v1/gpu/history?seconds=60", nil)
	rec := httptest.NewRecorder()
	s.gpuHistory(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var payload struct {
		Samples []GpuSample `json:"samples"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Samples) != 2 {
		t.Fatalf("samples = %d", len(payload.Samples))
	}
	if got := payload.Samples[0].Devices[0].UtilizationGPU; got == nil || *got != 37 {
		t.Fatalf("util = %v", got)
	}
}
