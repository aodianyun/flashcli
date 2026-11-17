package modelrun

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestHealthAcceptsHealthz(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	p := &process{endpoint: ts.URL, client: &http.Client{Timeout: 2 * time.Second}, done: make(chan struct{})}
	if err := p.Healthy(context.Background()); err != nil {
		t.Fatalf("Healthy with /healthz only: %v", err)
	}

	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer bad.Close()
	p2 := &process{endpoint: bad.URL, client: &http.Client{Timeout: 2 * time.Second}, done: make(chan struct{})}
	if err := p2.Healthy(context.Background()); err == nil {
		t.Fatal("Healthy accepted HTTP 503")
	}
}

func TestEndpointFromLog(t *testing.T) {
	cases := map[string]string{
		"  native-exec serve: http://127.0.0.1:55123 (no Python)": "http://127.0.0.1:55123",
		"native-exec serve: https://host:1/x":                     "https://host:1/x",
		"no marker here":                                          "",
		"native-exec serve: not-a-url":                            "",
	}
	for line, want := range cases {
		if got := endpointFromLog(line); got != want {
			t.Fatalf("endpointFromLog(%q) = %q, want %q", line, got, want)
		}
	}
}

func TestPortHelpers(t *testing.T) {
	port, err := FreePort()
	if err != nil {
		t.Fatal(err)
	}
	if !PortAvailable(port) {
		t.Fatalf("fresh port %d reported busy", port)
	}
	ln, err := net.Listen("tcp", "0.0.0.0:"+itoa(port))
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	if PortAvailable(port) {
		t.Fatalf("bound port %d reported free", port)
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var buf [6]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	return string(buf[i:])
}
