package setup

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestResolveBinary(t *testing.T) {
	dir := t.TempDir()
	plain := filepath.Join(dir, "flashserver")
	if err := os.WriteFile(plain, []byte("x"), 0o755); err != nil {
		t.Fatal(err)
	}
	if got := resolveBinary(dir, "flashserver", "linux", "amd64"); got != plain {
		t.Fatalf("resolveBinary = %q", got)
	}
	os.Remove(plain)
	versioned := filepath.Join(dir, "flashserver-linux-amd64")
	if err := os.WriteFile(versioned, []byte("x"), 0o755); err != nil {
		t.Fatal(err)
	}
	if got := resolveBinary(dir, "flashserver", "linux", "amd64"); got != versioned {
		t.Fatalf("resolveBinary = %q", got)
	}
}

func TestSystemdUnit(t *testing.T) {
	unit := systemdUnit(Options{
		User: "alice", Home: "/home/alice/.flashcli",
		ConfigPath: "/etc/flashserver/config.json", ServiceName: "flashserver",
	}, "/usr/local/bin")
	for _, want := range []string{
		"User=alice",
		"FLASHCLI_HOME=/home/alice/.flashcli",
		"ExecStart=/usr/local/bin/flashserver --config /etc/flashserver/config.json",
		"WantedBy=multi-user.target",
	} {
		if !strings.Contains(unit, want) {
			t.Fatalf("unit missing %q:\n%s", want, unit)
		}
	}
}
