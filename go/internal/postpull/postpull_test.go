package postpull

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestPaligemmaReadyMissing(t *testing.T) {
	if PaligemmaReady(filepath.Join(t.TempDir(), "nope.model")) {
		t.Fatal("missing file should not be ready")
	}
}

func TestRunUnknownStepIsNoop(t *testing.T) {
	env, err := Run(context.Background(), []any{map[string]any{"something": "else"}}, true)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if len(env) != 0 {
		t.Fatalf("env = %v", env)
	}
}

func TestEnsurePaligemmaMD5Mismatch(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("wrong-bytes"))
	}))
	defer srv.Close()

	oldURL := PaligemmaTokenizerURL
	oldClient := HTTPClient
	PaligemmaTokenizerURL = srv.URL
	HTTPClient = srv.Client()
	defer func() {
		PaligemmaTokenizerURL = oldURL
		HTTPClient = oldClient
	}()

	dest := filepath.Join(t.TempDir(), "pali.model")
	if _, err := EnsurePaligemma(context.Background(), dest, true, true); err == nil {
		t.Fatal("expected md5 mismatch")
	}
	if _, err := os.Stat(dest); err == nil {
		t.Fatal("dest should not exist after mismatch")
	}
}
