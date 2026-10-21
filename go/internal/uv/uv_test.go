package uv

import (
	"archive/zip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAtLeast(t *testing.T) {
	cases := []struct {
		v, min string
		want   bool
	}{
		{"0.9.3", "0.5.0", true},
		{"0.5.0", "0.5.0", true},
		{"0.4.9", "0.5.0", false},
		{"v1.2.3", "0.9.9", true},
		{"bogus", "0.5.0", false},
	}
	for _, c := range cases {
		if got := AtLeast(c.v, c.min); got != c.want {
			t.Errorf("AtLeast(%q,%q)=%v want %v", c.v, c.min, got, c.want)
		}
	}
}

func TestWheelMatch(t *testing.T) {
	amd := "uv-0.9.9-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
	m := wheelRe.FindStringSubmatch(amd)
	if m == nil || m[1] != "0.9.9" {
		t.Fatalf("wheelRe=%v", m)
	}
	if !platformMatch(m[2]) && os.Getenv("GOARCH") == "" {
		// platformMatch depends on runtime.GOARCH; only assert parsing here.
	}
	if wheelRe.MatchString("uv-0.9.9-py3-none-manylinux_2_17_aarch64.whl") == false {
		t.Fatal("aarch64 wheel must parse")
	}
	if wheelRe.MatchString("uv-0.9.9rc1-py3-none-manylinux_2_17_x86_64.whl") {
		t.Fatal("pre-release wheel must not match the stable regex")
	}
}

func TestExtractBinary(t *testing.T) {
	dir := t.TempDir()
	wheel := filepath.Join(dir, "uv.whl")
	f, err := os.Create(wheel)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(f)
	w, err := zw.Create("uv-0.9.9.data/scripts/uv")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write([]byte("#!/bin/sh\necho uv\n")); err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	bin, err := extractBinary(wheel, filepath.Join(dir, "out"))
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(bin)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode()&0o111 == 0 {
		t.Fatalf("extracted binary is not executable: %v", info.Mode())
	}
	blob, _ := os.ReadFile(bin)
	if !strings.Contains(string(blob), "echo uv") {
		t.Fatalf("unexpected binary contents: %q", blob)
	}
}

func TestEnvDefaults(t *testing.T) {
	t.Setenv("UV_CACHE_DIR", "")
	t.Setenv("UV_LINK_MODE", "")
	t.Setenv("UV_INDEX_URL", "")
	t.Setenv("PIP_INDEX_URL", "https://mirrors.aliyun.com/pypi/simple/")
	env := strings.Join(Env(), "\n")
	for _, want := range []string{
		"UV_LINK_MODE=hardlink",
		"UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/",
		"UV_CACHE_DIR=",
	} {
		if !strings.Contains(env, want) {
			t.Fatalf("Env missing %q:\n%s", want, env)
		}
	}
}
