package setup

import (
	"bytes"
	"context"
	"crypto/sha256"
	"debug/elf"
	"encoding/binary"
	"encoding/hex"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestEnsureAssetBinariesLocalWithSpacesDoesNotDownload(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "payload with spaces")
	writeTestLocalPayload(t, dir, testELF(t, elf.EM_X86_64, "test-version"), testELF(t, elf.EM_X86_64, "test-version"))

	requests := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		http.NotFound(w, r)
	}))
	defer srv.Close()

	opts := Options{BinDir: dir, ReleaseBase: srv.URL, ReleaseVersion: "1.0.0"}
	var out bytes.Buffer
	cleanup, err := ensureAssetBinariesFrom(context.Background(), Env{OS: "windows", Arch: "amd64"}, &opts, &out, t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	cleanup()
	if opts.BinDir != dir {
		t.Fatalf("BinDir = %q, want %q", opts.BinDir, dir)
	}
	if requests != 0 {
		t.Fatalf("local payload caused %d remote requests", requests)
	}
	if !strings.Contains(out.String(), "using verified local Linux payload") {
		t.Fatalf("output omitted local payload selection: %s", out.String())
	}
}

func TestEnsureAssetBinariesFindsPayloadBesideSetupExecutable(t *testing.T) {
	exeDir := filepath.Join(t.TempDir(), "installer payload")
	writeTestLocalPayload(t, exeDir, testELF(t, elf.EM_X86_64, "test-version"), testELF(t, elf.EM_X86_64, "test-version"))
	missingDir := filepath.Join(t.TempDir(), "missing payload")
	opts := Options{BinDir: missingDir}
	cleanup, err := ensureAssetBinariesFrom(context.Background(), Env{OS: "windows", Arch: "amd64"}, &opts, io.Discard, exeDir)
	if err != nil {
		t.Fatal(err)
	}
	cleanup()
	if opts.BinDir != exeDir {
		t.Fatalf("BinDir = %q, want executable directory %q", opts.BinDir, exeDir)
	}
}

func TestEnsureAssetBinariesRejectsIncompletePayloadWithoutDownload(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "flashcli-linux-amd64"), testELF(t, elf.EM_X86_64, "test-version"), 0o755); err != nil {
		t.Fatal(err)
	}
	requests := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		http.NotFound(w, r)
	}))
	defer srv.Close()
	opts := Options{BinDir: dir, ReleaseBase: srv.URL, ReleaseVersion: "1.0.0"}

	_, err := ensureAssetBinariesFrom(context.Background(), Env{OS: "windows", Arch: "amd64"}, &opts, io.Discard, t.TempDir())
	if err == nil || !strings.Contains(err.Error(), "incomplete payload") {
		t.Fatalf("error = %v, want explicit incomplete-payload error", err)
	}
	if requests != 0 {
		t.Fatalf("incomplete payload caused %d remote requests", requests)
	}
}

func TestReadLocalAssetsRejectsChecksumMismatch(t *testing.T) {
	dir := t.TempDir()
	cli := testELF(t, elf.EM_X86_64, "test-version")
	server := testELF(t, elf.EM_X86_64, "test-version")
	writeTestLocalPayload(t, dir, cli, server)
	cli[len(cli)-1] ^= 0xff
	if err := os.WriteFile(filepath.Join(dir, "flashcli-linux-amd64"), cli, 0o755); err != nil {
		t.Fatal(err)
	}

	_, found, err := readLocalAssets(dir, testAssetNames(), "amd64", "test-version")
	if !found || err == nil || !strings.Contains(err.Error(), "checksum mismatch") {
		t.Fatalf("found=%t error=%v, want checksum mismatch", found, err)
	}
}

func TestReadLocalAssetsRejectsArchitectureMismatch(t *testing.T) {
	dir := t.TempDir()
	writeTestLocalPayload(t, dir, testELF(t, elf.EM_AARCH64, "test-version"), testELF(t, elf.EM_X86_64, "test-version"))

	_, found, err := readLocalAssets(dir, testAssetNames(), "amd64", "test-version")
	if !found || err == nil || !strings.Contains(err.Error(), "expected EM_X86_64 for amd64") {
		t.Fatalf("found=%t error=%v, want architecture mismatch", found, err)
	}
}

func TestReadLocalAssetsRejectsVersionMismatch(t *testing.T) {
	dir := t.TempDir()
	writeTestLocalPayload(t, dir, testELF(t, elf.EM_X86_64, "1.0.0"), testELF(t, elf.EM_X86_64, "1.0.0"))

	_, found, err := readLocalAssets(dir, testAssetNames(), "amd64", "1.0.1")
	if !found || err == nil || !strings.Contains(err.Error(), `version marker "1.0.1" is missing`) {
		t.Fatalf("found=%t error=%v, want version mismatch", found, err)
	}
}

func TestEnsureAssetBinariesDownload(t *testing.T) {
	remote := map[string][]byte{
		"flashcli-linux-amd64":    []byte("cli"),
		"flashserver-linux-amd64": []byte("server"),
	}
	var sums string
	for name, data := range remote {
		sum := sha256.Sum256(data)
		sums += hex.EncodeToString(sum[:]) + "  " + name + "\n"
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1.0.0/sha256sums.txt" {
			_, _ = io.WriteString(w, sums)
			return
		}
		name := filepath.Base(r.URL.Path)
		data, ok := remote[name]
		if !ok {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write(data)
	}))
	defer srv.Close()

	t.Setenv("FLASHCLI_NO_MIRROR", "1")
	opts := Options{
		BinDir:         t.TempDir(),
		ReleaseBase:    srv.URL,
		ReleaseAPI:     srv.URL + "/api",
		ReleaseVersion: "1.0.0",
	}
	var out bytes.Buffer
	cleanup, err := ensureAssetBinariesFrom(context.Background(), Env{OS: "linux", Arch: "amd64"}, &opts, &out, t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	for name, want := range remote {
		got, err := os.ReadFile(filepath.Join(opts.BinDir, name))
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != string(want) {
			t.Fatalf("%s = %q", name, got)
		}
	}
	for _, want := range []string{"no local Linux payload found", "remote Linux payload source: " + srv.URL, "download " + srv.URL + "/v1.0.0/sha256sums.txt"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("output missing %q: %s", want, out.String())
		}
	}
}

func testAssetNames() []string {
	return []string{"flashcli-linux-amd64", "flashserver-linux-amd64"}
}

func writeTestLocalPayload(t *testing.T, dir string, cli, server []byte) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	assets := map[string][]byte{
		"flashcli-linux-amd64":    cli,
		"flashserver-linux-amd64": server,
	}
	var checksums strings.Builder
	for name, data := range assets {
		if err := os.WriteFile(filepath.Join(dir, name), data, 0o755); err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(data)
		checksums.WriteString(hex.EncodeToString(sum[:]) + "  " + name + "\n")
	}
	if err := os.WriteFile(filepath.Join(dir, checksumsAsset), []byte(checksums.String()), 0o644); err != nil {
		t.Fatal(err)
	}
}

func testELF(t *testing.T, machine elf.Machine, marker string) []byte {
	t.Helper()
	data := make([]byte, 64, 64+len(marker))
	copy(data[:4], []byte{0x7f, 'E', 'L', 'F'})
	data[elf.EI_CLASS] = byte(elf.ELFCLASS64)
	data[elf.EI_DATA] = byte(elf.ELFDATA2LSB)
	data[elf.EI_VERSION] = byte(elf.EV_CURRENT)
	binary.LittleEndian.PutUint16(data[16:18], uint16(elf.ET_DYN))
	binary.LittleEndian.PutUint16(data[18:20], uint16(machine))
	binary.LittleEndian.PutUint32(data[20:24], uint32(elf.EV_CURRENT))
	binary.LittleEndian.PutUint16(data[52:54], uint16(len(data)))
	return append(data, []byte(marker)...)
}
