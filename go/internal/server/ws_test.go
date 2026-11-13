package server

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"

	"github.com/aodianyun/flashcli/go/internal/gpu"
)

func TestWebSocketStreamsSystem(t *testing.T) {
	util := 42
	s := &Server{
		Started: time.Now(),
		GPU: func(context.Context) ([]gpu.Device, error) {
			return []gpu.Device{{Index: 0, Name: "test-gpu", MemoryTotal: 100, MemoryUsed: 10, UtilizationGPU: &util}}, nil
		},
	}
	srv := httptest.NewServer(s.Handler())
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/v1/ws"
	conn, _, err := websocket.Dial(ctx, url, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "")

	readType := func() string {
		_, blob, err := conn.Read(ctx)
		if err != nil {
			t.Fatal(err)
		}
		var payload struct {
			Type string `json:"type"`
		}
		if err := json.Unmarshal(blob, &payload); err != nil {
			t.Fatal(err)
		}
		return payload.Type
	}
	if got := readType(); got != "hello" {
		t.Fatalf("first message = %q", got)
	}
	if got := readType(); got != "system" {
		t.Fatalf("second message = %q", got)
	}
}
