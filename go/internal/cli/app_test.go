package cli

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testManifest = `{
  "format": "flashcli-application",
  "app_format_version": 1,
  "protocol_version": 1,
  "name": "demo",
  "version": "1.0.0",
  "display_name": "Demo",
  "supported": {"os": ["linux", "darwin", "windows"], "arch": ["x86_64", "arm64"]},
  "install": {"commands": {"linux": "echo install-ok", "darwin": "echo install-ok", "windows": "echo install-ok"}},
  "model": {"bundles": [{"bundle": "a/one:1", "default": true, "serve": {"options": {}}}]},
  "config": []
}`

func fakeFlashHub(t *testing.T) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	mux.HandleFunc("/api/v1/apps", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("page") == "" {
			t.Errorf("missing pagination")
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"code": 0,
			"data": map[string]any{
				"list": []map[string]any{{
					"id": 1, "name": "demo", "display_name": "Demo", "domain": "通用Agent",
					"version": "1.0.0", "organization": map[string]string{"name": "xym"},
					"supported_os": []string{"linux"}, "supported_arch": []string{"x86_64"},
					"model_bundles": []map[string]any{{"bundle": "a/one:1", "is_default": true}},
				}},
				"total": 1, "page": 1, "page_size": 20,
			},
		})
	})
	mux.HandleFunc("/api/v1/apps/xym/demo", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"code":0,"message":"success","data":` + testManifest + `}`))
	})
	return srv
}

func runAppCmd(t *testing.T, args ...string) (string, error) {
	t.Helper()
	cmd := New()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	cmd.SetArgs(args)
	err := cmd.Execute()
	return out.String(), err
}

func TestAppListAndShow(t *testing.T) {
	srv := fakeFlashHub(t)
	t.Setenv("FLASHCLI_FLASHHUB_API", srv.URL+"/api/v1/repos")

	out, err := runAppCmd(t, "app", "list")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "Demo") || !strings.Contains(out, "total 1") {
		t.Fatalf("list output = %s", out)
	}

	out, err = runAppCmd(t, "app", "show", "xym/demo")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "Demo 1.0.0") || !strings.Contains(out, "a/one:1") {
		t.Fatalf("show output = %s", out)
	}

	out, err = runAppCmd(t, "app", "show", "xym/demo", "--json")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, `"app_format_version": 1`) {
		t.Fatalf("json output = %s", out)
	}
}

func TestAppInstallDryRun(t *testing.T) {
	srv := fakeFlashHub(t)
	home := t.TempDir()
	t.Setenv("FLASHCLI_FLASHHUB_API", srv.URL+"/api/v1/repos")
	t.Setenv("FLASHCLI_HOME", home)

	out, err := runAppCmd(t, "app", "install", "xym/demo", "--dry-run")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "DRY RUN") || !strings.Contains(out, "echo install-ok") {
		t.Fatalf("dry-run output = %s", out)
	}
	if _, err := os.Stat(filepath.Join(home, "flashserver", "apps.json")); !os.IsNotExist(err) {
		t.Fatal("dry-run wrote app state")
	}
}

func TestAppStatusRequiresInstall(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if _, err := runAppCmd(t, "app", "status", "xym/demo"); err == nil {
		t.Fatal("expected not-installed error")
	}
}
