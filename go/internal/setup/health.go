package setup

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"
)

func waitHealth(ctx context.Context, addr, token string) error {
	if ctx == nil {
		ctx = context.Background()
	}
	// WSL's localhost relay may publish only one loopback family (::1 or
	// 127.0.0.1) depending on the Windows/WSL version, so probe both.
	var hosts []string
	if host, port, err := net.SplitHostPort(addr); err == nil {
		switch host {
		case "", "0.0.0.0", "::", "[::]":
			hosts = []string{net.JoinHostPort("127.0.0.1", port), net.JoinHostPort("localhost", port)}
		default:
			hosts = []string{addr, net.JoinHostPort("localhost", port)}
		}
	} else {
		hosts = []string{addr, "localhost:8790"}
	}
	deadline := time.Now().Add(20 * time.Second)
	client := &http.Client{Timeout: 2 * time.Second}
	for time.Now().Before(deadline) {
		for _, hostAddr := range hosts {
			url := hostAddr
			if !strings.Contains(url, "://") {
				url = "http://" + url
			}
			if !strings.HasSuffix(url, "/health") {
				url += "/health"
			}
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
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
	}
	return fmt.Errorf("flashserver health check failed at %s", addr)
}
