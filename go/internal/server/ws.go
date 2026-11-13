package server

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/coder/websocket"

	"github.com/aodianyun/flashcli/go/internal/version"
)

type wsClient struct {
	conn *websocket.Conn
	out  chan []byte
}

func (c *wsClient) send(v any) {
	blob, err := json.Marshal(v)
	if err != nil {
		return
	}
	c.sendBytes(blob)
}

func (c *wsClient) sendBytes(blob []byte) {
	select {
	case c.out <- blob:
	default: // slow client: drop rather than block the daemon
	}
}

func (c *wsClient) writeLoop(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case blob := <-c.out:
			wctx, cancel := context.WithTimeout(ctx, 5*time.Second)
			err := c.conn.Write(wctx, websocket.MessageText, blob)
			cancel()
			if err != nil {
				return
			}
		}
	}
}

// ws streams realtime snapshots (system/models/storage/mirror) and job progress.
func (s *Server) ws(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		return
	}
	defer conn.Close(websocket.StatusNormalClosure, "")

	client := &wsClient{conn: conn, out: make(chan []byte, 64)}
	s.addWSClient(client)
	defer s.removeWSClient(client)

	ctx := r.Context()
	go func() {
		for {
			if _, _, err := conn.Read(ctx); err != nil {
				return
			}
		}
	}()
	go client.writeLoop(ctx)

	client.send(map[string]any{
		"type":             "hello",
		"version":          version.Version,
		"protocol_version": version.ProtocolVersion,
	})
	client.send(map[string]any{"type": "system", "data": s.systemSnapshot(ctx)})
	s.sendWSSnapshots(ctx, client)

	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	snapTicker := time.NewTicker(2 * time.Second)
	defer snapTicker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			client.send(map[string]any{"type": "system", "data": s.systemSnapshot(ctx)})
		case <-snapTicker.C:
			s.sendWSSnapshots(ctx, client)
		}
	}
}

func (s *Server) sendWSSnapshots(ctx context.Context, client *wsClient) {
	if s.Source != nil {
		if models, err := s.Source.Models(ctx); err == nil {
			client.send(map[string]any{
				"type": "models",
				"data": map[string]any{"models": models, "loaded": s.loaded()},
			})
		}
		if areas, err := s.Source.Storage(ctx); err == nil {
			client.send(map[string]any{
				"type": "storage",
				"data": map[string]any{"areas": areas},
			})
		}
	}
	client.send(map[string]any{"type": "mirror", "data": mirrorPayload()})
}

func (s *Server) addWSClient(c *wsClient) {
	s.wsMu.Lock()
	if s.wsClients == nil {
		s.wsClients = map[*wsClient]struct{}{}
	}
	s.wsClients[c] = struct{}{}
	s.wsMu.Unlock()
}

func (s *Server) removeWSClient(c *wsClient) {
	s.wsMu.Lock()
	delete(s.wsClients, c)
	s.wsMu.Unlock()
}

func (s *Server) broadcastWS(v any) {
	blob, err := json.Marshal(v)
	if err != nil {
		return
	}
	s.wsMu.Lock()
	for c := range s.wsClients {
		c.sendBytes(blob)
	}
	s.wsMu.Unlock()
}

// forwardJobs pushes job progress to every WebSocket client.
func (s *Server) forwardJobs(ctx context.Context) {
	if s.Jobs == nil {
		return
	}
	ch, cancel := s.Jobs.Subscribe()
	defer cancel()
	for {
		select {
		case <-ctx.Done():
			return
		case u, ok := <-ch:
			if !ok {
				return
			}
			s.broadcastWS(map[string]any{"type": "job", "data": u})
		}
	}
}
