package system

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeExecutable(t *testing.T, dir, name, body string) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestParseCapabilities(t *testing.T) {
	got, err := Parse([]string{"python-headers", "c-compiler"})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join([]string{string(got[0]), string(got[1])}, ",") != "c-compiler,python-headers" {
		t.Fatalf("parse = %v", got)
	}
	for _, values := range [][]string{
		{"unknown"},
		{"c-compiler", "c-compiler"},
		{""},
	} {
		if _, err := Parse(values); err == nil {
			t.Fatalf("expected error for %v", values)
		}
	}
}

func TestPackagesFor(t *testing.T) {
	cases := []struct {
		mgr  Manager
		cap  Capability
		abi  string
		want string
	}{
		{APT, CCompiler, "312", "gcc libc6-dev"},
		{APT, CXXCompiler, "312", "g++"},
		{APT, PythonHeaders, "310", "python3.10-dev"},
		{DNF, CCompiler, "312", "gcc glibc-devel"},
		{DNF, CXXCompiler, "312", "gcc-c++"},
		{DNF, PythonHeaders, "312", "python3.12-devel"},
		{APK, CCompiler, "312", "gcc musl-dev"},
		{APK, CXXCompiler, "312", "g++"},
		{APK, PythonHeaders, "312", "python3-dev"},
		{ZYPPER, PythonHeaders, "312", "python312-devel"},
	}
	for _, tc := range cases {
		got := strings.Join(PackagesFor(tc.mgr, tc.cap, tc.abi), " ")
		if got != tc.want {
			t.Errorf("%s/%s/%s = %q, want %q", tc.mgr, tc.cap, tc.abi, got, tc.want)
		}
	}
}

func TestCheckCompilers(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "cc", "exit 0\n")
	writeExecutable(t, dir, "g++", "exit 0\n")
	t.Setenv("PATH", dir)
	statuses, err := Check(context.Background(), []string{"c-compiler", "cxx-compiler"}, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(statuses) != 2 || !statuses[0].Present || !statuses[1].Present {
		t.Fatalf("statuses = %+v", statuses)
	}
}

func TestCheckPythonHeaders(t *testing.T) {
	dir := t.TempDir()
	include := filepath.Join(dir, "include")
	if err := os.MkdirAll(include, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(include, "Python.h"), []byte("/* header */\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	py := writeExecutable(t, dir, "python", `echo '{"include":"`+include+`","platinclude":""}'`+"\n")
	statuses, err := Check(context.Background(), []string{"python-headers"}, py)
	if err != nil {
		t.Fatal(err)
	}
	if len(statuses) != 1 || !statuses[0].Present || !statuses[0].Checked {
		t.Fatalf("status = %+v", statuses)
	}
}

func TestCheckPythonHeadersNotReady(t *testing.T) {
	statuses, err := Check(context.Background(), []string{"python-headers"}, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(statuses) != 1 || statuses[0].Checked || statuses[0].Present {
		t.Fatalf("status = %+v", statuses)
	}
}

func TestMissing(t *testing.T) {
	missing := Missing([]Status{
		{Capability: CCompiler, Checked: true, Present: false},
		{Capability: CXXCompiler, Checked: true, Present: true},
		{Capability: PythonHeaders, Checked: false},
	})
	if len(missing) != 1 || missing[0] != CCompiler {
		t.Fatalf("missing = %v", missing)
	}
}

func TestInstallArgv(t *testing.T) {
	cases := map[Manager]string{
		APT:    "apt-get install -y gcc",
		DNF:    "dnf install -y gcc",
		YUM:    "yum install -y gcc",
		APK:    "apk add --no-cache gcc",
		ZYPPER: "zypper --non-interactive install gcc",
	}
	for mgr, want := range cases {
		got := strings.Join(installArgv(mgr, []string{"gcc"}), " ")
		if got != want {
			t.Errorf("%s = %q, want %q", mgr, got, want)
		}
	}
}

func TestAutoInstallDisabled(t *testing.T) {
	t.Setenv("FLASHCLI_AUTO_INSTALL_SYSTEM", "never")
	if AutoInstallEnabled() {
		t.Fatal("never must disable automatic installation")
	}
}
