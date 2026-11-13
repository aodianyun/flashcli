package setup

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestWaitHealthOK(t *testing.T) {
	var gotToken string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/health" {
			t.Errorf("path = %s", r.URL.Path)
		}
		gotToken = r.Header.Get("X-Flashcli-Token")
		w.WriteHeader(http.StatusOK)
	}))
	defer ts.Close()

	addr := strings.TrimPrefix(ts.URL, "http://")
	if err := waitHealth(context.Background(), addr, "secret"); err != nil {
		t.Fatalf("waitHealth: %v", err)
	}
	if gotToken != "secret" {
		t.Fatalf("token header = %q, want secret", gotToken)
	}
}

func TestWaitHealthHonorsContext(t *testing.T) {
	// Reserve and release a port so nothing listens there.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	_ = ln.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 700*time.Millisecond)
	defer cancel()
	start := time.Now()
	err = waitHealth(ctx, addr, "")
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("waitHealth error = %v, want deadline exceeded", err)
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Fatalf("waitHealth took %s", elapsed)
	}
}

func TestMirrorEnvContent(t *testing.T) {
	body := string(mirrorEnvContent())
	for _, want := range []string{
		"FLASHCLI_USE_MIRROR=1",
		"PIP_INDEX_URL=",
		"HF_ENDPOINT=",
		"FLASHCLI_INSTALL_REPO=https://gitee.com/aodiansoft/flashcli.git",
		"GOPROXY=https://goproxy.cn,direct",
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("mirror env missing %q:\n%s", want, body)
		}
	}
}

func TestDetect(t *testing.T) {
	env := Detect(context.Background())
	if env.OS == "" || env.Arch == "" {
		t.Fatalf("env = %+v", env)
	}
	if env.OS != "linux" {
		t.Skipf("host is %s; Linux assertions do not apply", env.OS)
	}
	if env.WSL {
		t.Fatal("WSL should not be reported on a native Linux host")
	}
}

func TestNormalizeDiagnostic(t *testing.T) {
	plain := []byte("wsl --status\nok\n")
	if got := normalizeDiagnostic(plain); string(got) != string(plain) {
		t.Fatalf("plain output changed: %q", got)
	}
	utf16 := []byte{'w', 0, 's', 0, 'l', 0, ' ', 0, 0x2d, 0x4e}
	if got := string(normalizeDiagnostic(utf16)); got != "wsl 中" {
		t.Fatalf("utf16 output = %q", got)
	}
}

func TestNormalizeOptionsDefaults(t *testing.T) {
	opts := normalizeOptions(Env{OS: "linux", Arch: "amd64"}, Options{})
	if opts.Backend != "auto" {
		t.Fatalf("backend = %q", opts.Backend)
	}
	if opts.Prefix != "/usr/local" {
		t.Fatalf("prefix = %q", opts.Prefix)
	}
	if opts.Distro != "flashserver_ubuntu" {
		t.Fatalf("distro = %q", opts.Distro)
	}
	if opts.Addr != "127.0.0.1:8790" {
		t.Fatalf("addr = %q", opts.Addr)
	}
	if opts.ServiceName != "flashserver" {
		t.Fatalf("service = %q", opts.ServiceName)
	}
	if opts.ConfigPath != "/etc/flashserver/config.json" {
		t.Fatalf("config = %q", opts.ConfigPath)
	}
	if opts.Home == "" || opts.User == "" {
		t.Fatalf("home/user not derived: %+v", opts)
	}
	if got := normalizeOptions(Env{OS: "linux"}, Options{Addr: "0.0.0.0:18790"}).Addr; got != "0.0.0.0:18790" {
		t.Fatalf("explicit addr = %q", got)
	}
}
