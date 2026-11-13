//go:build windows

package setup

import (
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestSelectAddrKeepsFreePort(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close()

	addr := net.JoinHostPort("127.0.0.1", strconv.Itoa(port))
	got, err := selectAddr(addr)
	if err != nil {
		t.Fatalf("selectAddr: %v", err)
	}
	if got != addr {
		t.Fatalf("selectAddr = %s, want %s", got, addr)
	}
}

func TestSelectAddrFallsBackWhenReserved(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	defer ln.Close()

	requested := net.JoinHostPort("127.0.0.1", strconv.Itoa(port))
	got, err := selectAddr(requested)
	if err != nil {
		t.Fatalf("selectAddr: %v", err)
	}
	if got == requested {
		t.Fatalf("selectAddr kept a busy port: %s", got)
	}
	if !strings.HasPrefix(got, "127.0.0.1:") {
		t.Fatalf("selectAddr = %s", got)
	}
}

func TestExposedAddr(t *testing.T) {
	for _, tc := range []struct{ in, want string }{
		{"127.0.0.1:8790", "0.0.0.0:8790"},
		{"localhost:18790", "0.0.0.0:18790"},
		{"0.0.0.0:8790", "0.0.0.0:8790"},
		{"10.0.0.5:9000", "10.0.0.5:9000"},
		{"not-an-addr", "0.0.0.0:8790"},
	} {
		if got := exposedAddr(tc.in); got != tc.want {
			t.Fatalf("exposedAddr(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestShellQuote(t *testing.T) {
	if got := shellQuote("plain"); got != "'plain'" {
		t.Fatalf("shellQuote = %q", got)
	}
	if got := shellQuote("a'b"); got != `'a'\''b'` {
		t.Fatalf("shellQuote = %q", got)
	}
}

func TestClientAPIURLRoundtrip(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("LOCALAPPDATA", dir)
	if got := clientAPIURL(); got != "http://localhost:8790" {
		t.Fatalf("default client API = %q", got)
	}
	if err := writeClientAPI("127.0.0.1:18790"); err != nil {
		t.Fatalf("writeClientAPI: %v", err)
	}
	blob, err := os.ReadFile(filepath.Join(dir, "FlashServer", "api-url.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(string(blob)) != "http://127.0.0.1:18790" {
		t.Fatalf("api-url.txt = %q", blob)
	}
	if got := clientAPIURL(); got != "http://127.0.0.1:18790" {
		t.Fatalf("client API = %q", got)
	}
}

func TestDistroMarkerAndKeepaliveScript(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("LOCALAPPDATA", dir)

	writeDistroMarker("flashserver_ubuntu")
	blob, err := os.ReadFile(filepath.Join(dir, "FlashServer", "distro.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(string(blob)) != "flashserver_ubuntu" {
		t.Fatalf("distro.txt = %q", blob)
	}

	opts := Options{Distro: "flashserver_ubuntu", ServiceName: "flashserver"}
	path, err := wslKeepaliveScript(opts)
	if err != nil {
		t.Fatalf("wslKeepaliveScript: %v", err)
	}
	script, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		`wsl.exe -d flashserver_ubuntu -u root systemctl start flashserver`,
		`wsl.exe -d flashserver_ubuntu -u root -e sleep infinity`,
	} {
		if !strings.Contains(string(script), want) {
			t.Fatalf("keepalive script missing %q:\n%s", want, script)
		}
	}

	dry := Options{Distro: "x", ServiceName: "y", DryRun: true}
	if _, err := wslKeepaliveScript(dry); err != nil {
		t.Fatalf("dry-run script: %v", err)
	}
}
