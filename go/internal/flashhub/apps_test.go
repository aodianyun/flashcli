package flashhub

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestParseAppRef(t *testing.T) {
	ok := map[string]AppRef{
		"xym/workbuddy":       {Org: "xym", Name: "workbuddy"},
		"xym/workbuddy:1.0.0": {Org: "xym", Name: "workbuddy", Version: "1.0.0"},
		"/xym/workbuddy/":     {Org: "xym", Name: "workbuddy"},
	}
	for in, want := range ok {
		got, err := ParseAppRef(in)
		if err != nil || got != want {
			t.Fatalf("ParseAppRef(%q) = %+v, %v; want %+v", in, got, err, want)
		}
	}
	for _, bad := range []string{"", "workbuddy", "a/b/c", "xym/"} {
		if _, err := ParseAppRef(bad); err == nil {
			t.Fatalf("ParseAppRef(%q) should fail", bad)
		}
	}
}

func TestAppsBaseDerivation(t *testing.T) {
	t.Setenv("FLASHCLI_FLASHHUB_API", "https://example.test/api/v1/repos")
	if got := AppsBase(); got != "https://example.test/api/v1/apps" {
		t.Fatalf("AppsBase = %q", got)
	}
	t.Setenv("FLASHCLI_FLASHHUB_API", "https://example.test/custom")
	if got := AppsBase(); got != "https://example.test/custom/apps" {
		t.Fatalf("AppsBase = %q", got)
	}
}

func TestListApps(t *testing.T) {
	var gotQuery string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotQuery = r.URL.RawQuery
		_ = json.NewEncoder(w).Encode(map[string]any{
			"code": 0,
			"data": map[string]any{
				"list": []map[string]any{{
					"id": 1, "name": "demo", "display_name": "Demo", "domain": "通用Agent",
					"version": "1.0.0", "organization": map[string]string{"name": "xym"},
					"supported_os": []string{"linux"}, "supported_arch": []string{"x86_64"},
					"install_commands": map[string]string{"linux": "echo"},
					"model_bundles":    []map[string]any{{"bundle": "a/b:1", "is_default": true}},
				}},
				"total": 1, "page": 1, "page_size": 20,
			},
		})
	}))
	defer srv.Close()
	t.Setenv("FLASHCLI_FLASHHUB_API", srv.URL+"/api/v1/repos")

	client := &Client{HTTP: srv.Client(), CacheDir: t.TempDir(), UserAgent: "test"}
	apps, total, err := client.ListApps(context.Background(), "demo", "通用Agent", 1, 20)
	if err != nil {
		t.Fatal(err)
	}
	if total != 1 || len(apps) != 1 || apps[0].Name != "demo" {
		t.Fatalf("apps=%+v total=%d", apps, total)
	}
	if apps[0].InstallCommands["linux"] != "echo" || len(apps[0].ModelBundles) != 1 || !apps[0].ModelBundles[0].IsDefault {
		t.Fatalf("app = %+v", apps[0])
	}
	if !strings.Contains(gotQuery, "search=demo") || !strings.Contains(gotQuery, "page_size=20") {
		t.Fatalf("query = %q", gotQuery)
	}
}
