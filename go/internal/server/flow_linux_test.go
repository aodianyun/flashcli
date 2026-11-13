//go:build linux

package server

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// TestMain doubles as a fake `flashcli serve`: when FLASHSERVER_TEST_SERVE is
// set the test binary serves /health and /v1/chat/completions instead of
// running tests, so the real FlashcliLauncher can be exercised end to end.
func TestMain(m *testing.M) {
	if os.Getenv("FLASHSERVER_TEST_SERVE") == "1" {
		os.Exit(fakeServeMain())
	}
	os.Exit(m.Run())
}

func fakeServeMain() int {
	host, port := "127.0.0.1", 0
	for i, arg := range os.Args {
		if i+1 >= len(os.Args) {
			continue
		}
		switch arg {
		case "--host":
			host = os.Args[i+1]
		case "--port":
			port, _ = strconv.Atoi(os.Args[i+1])
		}
	}
	fmt.Printf("fake serve %s:%d args=%s\n", host, port, strings.Join(os.Args[1:], " "))

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, `{"status":"ok"}`)
	})
	mux.HandleFunc("/v1/chat/completions", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"fake","choices":[]}`)
	})
	ln, err := net.Listen("tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		fmt.Fprintln(os.Stderr, "listen:", err)
		return 1
	}
	srv := &http.Server{Handler: mux}
	go func() { _ = srv.Serve(ln) }()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	<-sig
	_ = srv.Close()
	return 0
}

func waitHealthy(t *testing.T, p ServeProcess) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	var last error
	for time.Now().Before(deadline) {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		last = p.Healthy(ctx)
		cancel()
		if last == nil {
			return
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatalf("process never became healthy: %v", last)
}

func TestFlashcliLauncherStartsRealProcess(t *testing.T) {
	logDir := t.TempDir()
	launcher := FlashcliLauncher{
		Bin:      os.Args[0],
		LogDir:   logDir,
		ExtraEnv: []string{"FLASHSERVER_TEST_SERVE=1"},
	}
	port, err := freePort()
	if err != nil {
		t.Fatal(err)
	}
	p, err := launcher.Start(context.Background(), "demo:1", port)
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer func() { _ = p.Stop(context.Background()) }()

	if p.PID() == 0 || !p.Running() {
		t.Fatalf("process not running: pid=%d", p.PID())
	}
	if want := fmt.Sprintf("http://127.0.0.1:%d", port); p.Endpoint() != want {
		t.Fatalf("endpoint = %s, want %s", p.Endpoint(), want)
	}
	waitHealthy(t, p)
	if portAvailable(port) {
		t.Fatal("launched process did not bind the port")
	}
	if log := p.LastLog(); !strings.Contains(log, "fake serve") {
		t.Fatalf("LastLog = %q", log)
	}
	if _, err := os.Stat(logDir + "/demo_1.log"); err != nil {
		t.Fatalf("serve log missing: %v", err)
	}

	if err := p.Stop(context.Background()); err != nil {
		t.Fatalf("Stop: %v", err)
	}
	if p.Running() {
		t.Fatal("process still running after Stop")
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if portAvailable(port) {
			return
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatal("port was not released after Stop")
}

func TestFlashcliLauncherOptionsAndFlags(t *testing.T) {
	launcher := FlashcliLauncher{
		Bin:      os.Args[0],
		Host:     "0.0.0.0",
		LogDir:   t.TempDir(),
		ExtraEnv: []string{"FLASHSERVER_TEST_SERVE=1"},
	}
	port, err := freePort()
	if err != nil {
		t.Fatal(err)
	}
	p, err := launcher.StartWithOptions(context.Background(), "demo:2", LoadOptions{
		Port:  port,
		Flags: []string{"--max-seq", "128"},
	})
	if err != nil {
		t.Fatalf("StartWithOptions: %v", err)
	}
	defer func() { _ = p.Stop(context.Background()) }()

	if want := fmt.Sprintf("http://127.0.0.1:%d", port); p.Endpoint() != want {
		t.Fatalf("endpoint = %s, want %s", p.Endpoint(), want)
	}
	waitHealthy(t, p)
	if log := p.LastLog(); !strings.Contains(log, "--max-seq 128") || !strings.Contains(log, "0.0.0.0") {
		t.Fatalf("LastLog = %q", log)
	}
}

func TestFlashcliProcessHealthAcceptsHealthz(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	p := &flashcliProcess{
		endpoint: ts.URL,
		client:   &http.Client{Timeout: 2 * time.Second},
		done:     make(chan struct{}),
	}
	if err := p.Healthy(context.Background()); err != nil {
		t.Fatalf("Healthy with /healthz only: %v", err)
	}

	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer bad.Close()
	p2 := &flashcliProcess{endpoint: bad.URL, client: &http.Client{Timeout: 2 * time.Second}, done: make(chan struct{})}
	if err := p2.Healthy(context.Background()); err == nil {
		t.Fatal("Healthy accepted HTTP 503")
	}
}

func TestPortHelpers(t *testing.T) {
	port, err := freePort()
	if err != nil {
		t.Fatal(err)
	}
	if !portAvailable(port) {
		t.Fatalf("fresh port %d reported busy", port)
	}
	ln, err := net.Listen("tcp", fmt.Sprintf("0.0.0.0:%d", port))
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	if portAvailable(port) {
		t.Fatalf("bound port %d reported free", port)
	}
}
