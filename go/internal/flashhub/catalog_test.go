package flashhub

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCatalogListAndVersions(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/tags":
			fmt.Fprint(w, `{"code":0,"data":[{"id":1,"name":"VLA","name_cn":"VLA"}]}`)
		case "/repositories":
			if got := r.URL.Query().Get("search"); got != "pi05" {
				t.Errorf("search = %q", got)
			}
			if got := r.URL.Query().Get("tag_id"); got != "1" {
				t.Errorf("tag_id = %q", got)
			}
			fmt.Fprint(w, `{"code":0,"data":{"total":1,"page":1,"page_size":20,"list":[{"id":5,"name":"pi05_libero","model_name":"lerobot/pi05","version_count":4,"downloads":9,"organization":{"name":"flashcli-bundle"}}]}}`)
		case "/repositories/5/versions":
			fmt.Fprint(w, `{"code":0,"data":{"total":2,"list":[{"id":26,"version":"1.0.4","size":471834099,"file_count":52,"release_status":"released"},{"id":10,"version":"1.0.3","size":471830588,"file_count":51,"release_status":"released"}]}}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	t.Setenv("FLASHCLI_FLASHHUB_WEB_API", srv.URL)

	ctx := context.Background()
	c := NewClient()
	tags, err := c.ListTags(ctx)
	if err != nil || len(tags) != 1 || tags[0].Name != "VLA" {
		t.Fatalf("tags=%+v err=%v", tags, err)
	}
	repos, total, err := c.ListRepositories(ctx, "pi05", 1, "updated", 1, 20)
	if err != nil {
		t.Fatal(err)
	}
	if total != 1 || len(repos) != 1 {
		t.Fatalf("repos=%+v total=%d", repos, total)
	}
	if repos[0].Namespace != "flashcli-bundle" || repos[0].Name != "pi05_libero" {
		t.Fatalf("repo = %+v", repos[0])
	}
	versions, vtotal, err := c.ListVersions(ctx, 5, 1, 20)
	if err != nil || vtotal != 2 || versions[0].Version != "1.0.4" {
		t.Fatalf("versions=%+v total=%d err=%v", versions, vtotal, err)
	}
}

func TestCatalogEmptyListIsNotAnError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/repositories":
			fmt.Fprint(w, `{"code":0,"message":"success","data":{"list":null,"total":0,"page":1,"page_size":20}}`)
		case "/tags":
			fmt.Fprint(w, `{"code":0,"data":null}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	t.Setenv("FLASHCLI_FLASHHUB_WEB_API", srv.URL)

	ctx := context.Background()
	c := NewClient()
	repos, total, err := c.ListRepositories(ctx, "spark_x26_1p7b", 1, "updated", 1, 20)
	if err != nil {
		t.Fatalf("empty result must not be an error: %v", err)
	}
	if repos == nil {
		t.Fatal("empty result must be an empty slice, not nil (JSON null)")
	}
	if total != 0 || len(repos) != 0 {
		t.Fatalf("repos=%d total=%d", len(repos), total)
	}
	tags, err := c.ListTags(ctx)
	if err != nil || tags == nil {
		t.Fatalf("tags=%v err=%v", tags, err)
	}
}

func TestCatalogAPIError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"code":500,"message":"boom"}`)
	}))
	defer srv.Close()
	t.Setenv("FLASHCLI_FLASHHUB_WEB_API", srv.URL)
	if _, _, err := NewClient().ListRepositories(context.Background(), "", 0, "", 1, 5); err == nil {
		t.Fatal("expected error")
	}
}
