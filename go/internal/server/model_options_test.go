package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func optionsTestBundle(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	data := `{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "protocol_version": 1,
  "name": "options-test",
  "python_abi": "310",
  "entry": {"serve": {"module": "serve", "attr": "ServeEngine"}},
  "python_dependencies": {"pip": []},
  "runtime": {"sm89-cu124-linux-x86_64-py310": "runtime/test"},
  "serve_options": [
    {"name": "max_seq", "type": "integer", "default": 2048, "help": "context"},
    {"name": "device", "type": "string", "default": "cuda:0", "help": "torch device"}
  ]
}`
	if err := os.WriteFile(filepath.Join(dir, "flashcli-bundle.json"), []byte(data), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestModelOptionsAPI(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	dir := optionsTestBundle(t)
	s := &Server{ServeSettings: newServeSettingsStore("")}
	ref := url.QueryEscape(dir)

	req := httptest.NewRequest(http.MethodGet, "/v1/models/options?ref="+ref, nil)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("GET status = %d: %s", rec.Code, rec.Body.String())
	}
	var got map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got["host"] != "127.0.0.1" {
		t.Fatalf("default host = %v", got["host"])
	}
	options, _ := got["options"].([]any)
	if len(options) != 2 {
		t.Fatalf("options = %s", rec.Body.String())
	}

	put := `{"ref":` + quoteJSON(dir) + `,"host":"0.0.0.0","port":0,"options":{"max_seq":"8192","device":"cuda:1"}}`
	req = httptest.NewRequest(http.MethodPut, "/v1/models/options", stringsReader(put))
	req.Header.Set("Content-Type", "application/json")
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("PUT status = %d: %s", rec.Code, rec.Body.String())
	}
	saved := s.ServeSettings.Get(dir)
	if saved.Host != "0.0.0.0" || saved.Options["max_seq"] != "8192" {
		t.Fatalf("saved = %+v", saved)
	}

	// Invalid values are rejected.
	bad := `{"ref":` + quoteJSON(dir) + `,"options":{"max_seq":"nope"}}`
	req = httptest.NewRequest(http.MethodPut, "/v1/models/options", stringsReader(bad))
	req.Header.Set("Content-Type", "application/json")
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("invalid PUT status = %d: %s", rec.Code, rec.Body.String())
	}

	req = httptest.NewRequest(http.MethodDelete, "/v1/models/options?ref="+ref, nil)
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("DELETE status = %d", rec.Code)
	}
	if got := s.ServeSettings.Get(dir); got.Host != "" || len(got.Options) != 0 {
		t.Fatalf("reset settings = %+v", got)
	}
}

func TestLoadPassesSavedServeOptions(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	dir := optionsTestBundle(t)
	store := newServeSettingsStore("")
	if err := store.Set(dir, ModelServeSettings{
		Host:    "0.0.0.0",
		Options: map[string]string{"max_seq": "8192"},
	}); err != nil {
		t.Fatal(err)
	}
	l := &optionFakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{ServeSettings: store})
	if _, err := m.Load(context.Background(), dir); err != nil {
		t.Fatal(err)
	}
	if l.opts.Host != "0.0.0.0" {
		t.Fatalf("host = %q", l.opts.Host)
	}
	if l.opts.Port <= 0 {
		t.Fatalf("port = %d", l.opts.Port)
	}
	found := false
	for i := 0; i+1 < len(l.opts.Flags); i++ {
		if l.opts.Flags[i] == "--max-seq" && l.opts.Flags[i+1] == "8192" {
			found = true
		}
	}
	if !found {
		t.Fatalf("flags = %#v", l.opts.Flags)
	}
}

type optionFakeLauncher struct {
	opts LoadOptions
}

func (l *optionFakeLauncher) Start(context.Context, string, int) (ServeProcess, error) {
	return &fakeServe{ref: "x", endpoint: "http://127.0.0.1:1"}, nil
}

func (l *optionFakeLauncher) StartWithOptions(_ context.Context, ref string, opts LoadOptions) (ServeProcess, error) {
	l.opts = opts
	return &fakeServe{ref: ref, endpoint: "http://127.0.0.1:1"}, nil
}

func quoteJSON(s string) string {
	blob, _ := json.Marshal(s)
	return string(blob)
}

func stringsReader(s string) *strings.Reader { return strings.NewReader(s) }
