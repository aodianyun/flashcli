package setup

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

func waitHealth(ctx context.Context, addr, token string) error {
	if ctx == nil {
		ctx = context.Background()
	}
	healthAddr := strings.Replace(addr, "0.0.0.0:", "127.0.0.1:", 1)
	url := "http://" + healthAddr + "/health"
	deadline := time.Now().Add(20 * time.Second)
	client := &http.Client{Timeout: 2 * time.Second}
	for time.Now().Before(deadline) {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err == nil {
			if token != "" {
				req.Header.Set("X-Flashcli-Token", token)
			}
			resp, err := client.Do(req)
			if err == nil {
				_, _ = io.Copy(io.Discard, resp.Body)
				resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					return nil
				}
			}
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
	}
	return fmt.Errorf("flashserver health check failed at %s", url)
}
