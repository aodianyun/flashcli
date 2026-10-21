package venv

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/mirror"
	"github.com/aodianyun/flashcli/go/internal/runtime"
)

type benchBundle struct{ name, path string }

// Opt-in real benchmark: FLASHCLI_UV_BENCH=1 go test ./internal/venv -run TestUVBundleBench -v
// Creates one uv venv per bundle under the real FLASHCLI_HOME (removed after),
// keeping the uv cache so later bundles reuse the heavy torch/CUDA layer.
func TestUVBundleBench(t *testing.T) {
	if os.Getenv("FLASHCLI_UV_BENCH") != "1" {
		t.Skip("set FLASHCLI_UV_BENCH=1 to run the uv venv benchmark")
	}
	os.Setenv("FLASHCLI_VENV_BACKEND", "uv")
	os.Setenv("FLASHCLI_USE_MIRROR", "1")
	os.Setenv("PIP_INDEX_URL", "https://mirrors.aliyun.com/pypi/simple/")
	os.Setenv("PIP_TRUSTED_HOST", "mirrors.aliyun.com")
	os.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", "/app/flashcli/flashcli-bundle[infer]")
	mirror.Apply()

	bundles := []benchBundle{
		{"qwen_nvfp4", "/root/.flashcli/bundles/qwen_nvfp4/1.0.1/flashcli-bundle.json"},
		{"pi05_libero", "/root/.flashcli/bundles/pi05_libero/1.0.4/flashcli-bundle.json"},
		{"groot_n16", "/app/flashcli/bundles/groot_n16/flashcli-bundle.json"},
		{"qwen3_vl_nvfp4", "/app/flashcli/bundles/qwen3_vl_nvfp4/flashcli-bundle.json"},
		{"openvla_oft", "/root/.flashcli/bundles/openvla_oft/1.0.0/flashcli-bundle.json"},
		{"groot_n17", "/app/flashcli/bundles/groot_n17/flashcli-bundle.json"},
	}
	if custom := strings.TrimSpace(os.Getenv("FLASHCLI_UV_BENCH_BUNDLES")); custom != "" {
		bundles = nil
		for _, item := range strings.Split(custom, ",") {
			name, path, ok := strings.Cut(strings.TrimSpace(item), "=")
			if ok {
				bundles = append(bundles, benchBundle{name, path})
			}
		}
	}

	var ids []string
	seenGlobal := map[[2]uint64]bool{}
	defer func() {
		for _, id := range ids {
			_ = os.RemoveAll(runtime.Dir(id))
		}
	}()

	for _, b := range bundles {
		data, err := os.ReadFile(b.path)
		if err != nil {
			t.Logf("%-16s SKIP (no manifest: %v)", b.name, err)
			continue
		}
		var raw map[string]any
		if err := json.Unmarshal(data, &raw); err != nil {
			t.Logf("%-16s SKIP (json: %v)", b.name, err)
			continue
		}
		m, err := manifest.LoadData(raw, filepath.Dir(b.path))
		if err != nil {
			t.Logf("%-16s SKIP (manifest: %v)", b.name, err)
			continue
		}
		id := "uvbench-" + sanitize(b.name)
		ids = append(ids, id)
		start := time.Now()
		py, err := Ensure(context.Background(), id, m, Options{Quiet: true, Force: true})
		dur := time.Since(start)
		if err != nil {
			t.Logf("%-16s abi=%s FAIL %6.1fs: %v", b.name, m.PythonABIOrEmpty(), dur.Seconds(), err)
			continue
		}
		apparent, unique := dirUsage(runtime.VenvDir(id), seenGlobal)
		t.Logf("%-16s abi=%s dur=%6.1fs  apparent=%7s  unique=%7s  %s",
			b.name, m.PythonABIOrEmpty(), dur.Seconds(), human(apparent), human(unique), py)
	}
}

func sanitize(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(s) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '-' || r == '_' {
			b.WriteRune(r)
		} else {
			b.WriteRune('-')
		}
	}
	return b.String()
}

// dirUsage returns (apparent bytes, unique bytes by dev+inode).
func dirUsage(root string, seen map[[2]uint64]bool) (int64, int64) {
	var apparent, unique int64
	_ = filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil || info == nil || info.IsDir() {
			return nil
		}
		apparent += info.Size()
		if st, ok := info.Sys().(*syscall.Stat_t); ok {
			key := [2]uint64{uint64(st.Dev), uint64(st.Ino)}
			if !seen[key] {
				seen[key] = true
				unique += info.Size()
			}
		} else {
			unique += info.Size()
		}
		return nil
	})
	return apparent, unique
}

func human(n int64) string {
	const unit = 1024
	if n < unit {
		return fmt.Sprintf("%dB", n)
	}
	div, exp := int64(unit), 0
	for m := n / unit; m >= unit; m /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f%c", float64(n)/float64(div), "KMGTPE"[exp])
}
