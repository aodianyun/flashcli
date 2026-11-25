package server

import (
	"context"
	"net/http"
	"testing"
)

func TestGatewayModelList(t *testing.T) {
	s := newFlowServer(t, &staticLauncher{endpoint: "http://127.0.0.1:1"})
	h := s.Handler()

	rec, body := call(t, h, http.MethodGet, "/v1/models", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /v1/models = %d: %s", rec.Code, rec.Body.String())
	}
	if body["object"] != "list" {
		t.Fatalf("object = %v", body["object"])
	}
	data, ok := body["data"].([]any)
	if !ok || len(data) != 0 {
		t.Fatalf("data = %v", body["data"])
	}

	if _, err := s.Manager.LoadFor(context.Background(), "demo:1", "gateway-test"); err != nil {
		t.Fatalf("load: %v", err)
	}

	rec, body = call(t, h, http.MethodGet, "/v1/models", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /v1/models after load = %d: %s", rec.Code, rec.Body.String())
	}
	data, ok = body["data"].([]any)
	if !ok || len(data) != 1 {
		t.Fatalf("data = %v", body["data"])
	}
	model, ok := data[0].(map[string]any)
	if !ok {
		t.Fatalf("entry = %v", data[0])
	}
	if model["id"] != "demo:1" {
		t.Fatalf("id = %v", model["id"])
	}
	if model["object"] != "model" {
		t.Fatalf("entry object = %v", model["object"])
	}
	if model["owned_by"] != "flashcli" {
		t.Fatalf("owned_by = %v", model["owned_by"])
	}
}

func TestManagementRoutesAreNotOnV1(t *testing.T) {
	s := newFlowServer(t, &staticLauncher{endpoint: "http://127.0.0.1:1"})
	h := s.Handler()

	for _, tc := range []struct {
		method string
		path   string
	}{
		{http.MethodGet, "/v1/system"},
		{http.MethodGet, "/v1/storage"},
		{http.MethodPost, "/v1/models/load"},
		{http.MethodPost, "/v1/pull"},
		{http.MethodGet, "/v1/apps"},
	} {
		rec, _ := call(t, h, tc.method, tc.path, `{}`)
		if rec.Code >= 200 && rec.Code < 300 {
			t.Fatalf("%s %s unexpectedly succeeded with %d", tc.method, tc.path, rec.Code)
		}
	}
}
