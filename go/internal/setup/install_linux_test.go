//go:build linux

package setup

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// withRoot fakes a root install and restores the real check afterwards.
func withRoot(t *testing.T) {
	t.Helper()
	old := geteuid
	geteuid = func() int { return 0 }
	t.Cleanup(func() { geteuid = old })
}

// fakeSystemctl puts a no-op systemctl first on PATH and returns its log file.
func fakeSystemctl(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	log := filepath.Join(dir, "calls.log")
	script := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> '" + log + "'\n"
	if err := os.WriteFile(filepath.Join(dir, "systemctl"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	return log
}

type linuxInstall struct {
	dir    string
	bin    string
	prefix string
	home   string
	config string
	opts   Options
}

func prepareLinuxInstall(t *testing.T) linuxInstall {
	t.Helper()
	dir := t.TempDir()
	bin := filepath.Join(dir, "assets")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"flashcli", "flashserver"} {
		if err := os.WriteFile(filepath.Join(bin, name), []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	li := linuxInstall{
		dir:    dir,
		bin:    bin,
		prefix: filepath.Join(dir, "prefix"),
		home:   filepath.Join(dir, "home"),
		config: filepath.Join(dir, "etc", "flashserver", "config.json"),
	}
	li.opts = Options{
		Backend:     "native",
		BinDir:      bin,
		Prefix:      li.prefix,
		Home:        li.home,
		User:        "root",
		ServiceName: "flashserver-unittest",
		ConfigPath:  li.config,
		Addr:        "127.0.0.1:18790",
		Token:       "unit-token",
		NoService:   true,
	}
	return li
}

func TestRunDiagDecodesChildOutput(t *testing.T) {
	var buf bytes.Buffer
	oldDiag := diag
	SetLog(&buf)
	t.Cleanup(func() { diag = oldDiag })

	i := installer{env: Env{OS: "linux", Arch: "amd64"}, out: io.Discard}
	if err := i.runDiag(context.Background(), "sh", "-c", `printf 'a\000b\000'`); err != nil {
		t.Fatalf("runDiag: %v", err)
	}
	if got := buf.String(); got != "ab" {
		t.Fatalf("diag = %q", got)
	}
	if err := i.runDiag(context.Background(), "sh", "-c", `printf 'plain'`); err != nil {
		t.Fatalf("runDiag: %v", err)
	}
	if got := buf.String(); got != "abplain" {
		t.Fatalf("diag after plain output = %q", got)
	}
}

func TestInstallLinuxNoService(t *testing.T) {
	withRoot(t)
	fakeSystemctl(t)
	li := prepareLinuxInstall(t)

	var out bytes.Buffer
	if err := Run(context.Background(), Env{OS: "linux", Arch: "amd64"}, li.opts, &out); err != nil {
		t.Fatalf("Run: %v\n%s", err, out.String())
	}
	for _, name := range []string{"flashcli", "flashserver"} {
		path := filepath.Join(li.prefix, "bin", name)
		info, err := os.Stat(path)
		if err != nil {
			t.Fatalf("missing %s: %v", path, err)
		}
		if info.Mode().Perm() != 0o755 {
			t.Fatalf("%s mode = %v", path, info.Mode().Perm())
		}
	}
	if !strings.Contains(out.String(), "service install skipped") {
		t.Fatalf("output missing NoService hint:\n%s", out.String())
	}

	blob, err := os.ReadFile(li.config)
	if err != nil {
		t.Fatalf("config: %v", err)
	}
	var cfg map[string]any
	if err := json.Unmarshal(blob, &cfg); err != nil {
		t.Fatalf("config JSON: %v\n%s", err, blob)
	}
	if cfg["addr"] != "127.0.0.1:18790" || cfg["token"] != "unit-token" {
		t.Fatalf("config = %v", cfg)
	}
	if cfg["flashcli_bin"] != filepath.Join(li.prefix, "bin", "flashcli") {
		t.Fatalf("flashcli_bin = %v", cfg["flashcli_bin"])
	}
	info, err := os.Stat(li.config)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("config mode = %v (%v)", info, err)
	}

	env, err := os.ReadFile(filepath.Join(li.home, "mirror.env"))
	if err != nil {
		t.Fatalf("mirror.env: %v", err)
	}
	if !strings.Contains(string(env), "PIP_INDEX_URL=") || !strings.Contains(string(env), "FLASHCLI_USE_MIRROR=1") {
		t.Fatalf("mirror.env = %s", env)
	}
}

func TestUninstallLinuxKeepsModelData(t *testing.T) {
	withRoot(t)
	calls := fakeSystemctl(t)
	li := prepareLinuxInstall(t)

	if err := Run(context.Background(), Env{OS: "linux", Arch: "amd64"}, li.opts, &bytes.Buffer{}); err != nil {
		t.Fatalf("install: %v", err)
	}

	opts := li.opts
	opts.Uninstall = true
	opts.RemoveCLI = true
	var out bytes.Buffer
	if err := Run(context.Background(), Env{OS: "linux", Arch: "amd64"}, opts, &out); err != nil {
		t.Fatalf("uninstall: %v\n%s", err, out.String())
	}
	if _, err := os.Stat(li.config); !os.IsNotExist(err) {
		t.Fatalf("config still exists: %v", err)
	}
	for _, name := range []string{"flashcli", "flashserver"} {
		if _, err := os.Stat(filepath.Join(li.prefix, "bin", name)); !os.IsNotExist(err) {
			t.Fatalf("%s still exists: %v", name, err)
		}
	}
	if _, err := os.Stat(filepath.Join(li.home, "mirror.env")); err != nil {
		t.Fatalf("model data was not kept: %v", err)
	}
	log, err := os.ReadFile(calls)
	if err != nil {
		t.Fatalf("systemctl log: %v", err)
	}
	if !strings.Contains(string(log), "disable --now flashserver-unittest") {
		t.Fatalf("systemctl calls = %s", log)
	}
}

func TestLinuxServiceControlWritesMarker(t *testing.T) {
	withRoot(t)
	calls := fakeSystemctl(t)
	marker := filepath.Join(t.TempDir(), "autostart")
	oldMarker := autostartMarker
	autostartMarker = marker
	t.Cleanup(func() { autostartMarker = oldMarker })

	li := prepareLinuxInstall(t)
	env := Env{OS: "linux", Arch: "amd64"}

	run := func(mutate func(*Options), wantMarker string) string {
		t.Helper()
		opts := li.opts
		mutate(&opts)
		var out bytes.Buffer
		if err := Run(context.Background(), env, opts, &out); err != nil {
			t.Fatalf("Run: %v\n%s", err, out.String())
		}
		blob, err := os.ReadFile(marker)
		if err != nil {
			t.Fatalf("marker: %v", err)
		}
		if strings.TrimSpace(string(blob)) != wantMarker {
			t.Fatalf("marker = %q, want %q", blob, wantMarker)
		}
		return out.String()
	}

	run(func(o *Options) { o.StopService = true }, "disabled")
	run(func(o *Options) { o.EnableAutostart = true }, "enabled")
	run(func(o *Options) { o.DisableAutostart = true }, "disabled")
	out := run(func(o *Options) { o.StartService = true }, "enabled")
	if !strings.Contains(out, "Console:") {
		t.Fatalf("start output = %s", out)
	}

	log, err := os.ReadFile(calls)
	if err != nil {
		t.Fatalf("systemctl log: %v", err)
	}
	for _, want := range []string{
		"disable --now flashserver-unittest",
		"enable flashserver-unittest",
		"disable flashserver-unittest",
		"enable --now flashserver-unittest",
	} {
		if !strings.Contains(string(log), want) {
			t.Fatalf("systemctl calls missing %q:\n%s", want, log)
		}
	}
}
