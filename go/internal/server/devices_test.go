package server

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
)

func placementManifestData(envs []string, resources map[string]any) map[string]any {
	defaults := map[string]any{
		"python_abi": "312",
		"entry": map[string]any{
			"run":   map[string]any{"kind": "python", "module": "run", "attr": "RunEngine"},
			"serve": map[string]any{"kind": "python", "module": "serve", "attr": "ServeEngine"},
		},
	}
	if resources != nil {
		defaults["resources"] = resources
	}
	envMap := map[string]any{}
	for _, key := range envs {
		envMap[key] = map[string]any{"runtime": "runtime/" + key}
	}
	return map[string]any{
		"format": manifest.Format, "format_version": 4, "protocol_version": 1,
		"name": "demo", "defaults": defaults, "environments": envMap,
	}
}

func placementManifest(t *testing.T, envs []string, resources map[string]any) *manifest.Manifest {
	t.Helper()
	m, err := manifest.LoadData(placementManifestData(envs, resources), t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func twoGPUInventory(freeSecond int64) DeviceInventory {
	return inventoryFrom([]gpu.Device{
		{Index: 0, Name: "RTX 4090", MemoryTotal: 24 << 30, MemoryUsed: 4 << 30, MemoryFree: 20 << 30, ComputeCap: "8.9"},
		{Index: 1, Name: "RTX 5090", MemoryTotal: 32 << 30, MemoryUsed: 32<<30 - freeSecond, MemoryFree: freeSecond, ComputeCap: "12.0"},
	}, "")
}

func TestPlacementSingleAndMultiGPU(t *testing.T) {
	inv := twoGPUInventory(28 << 30)
	m := placementManifest(t, []string{
		"sm89-cu124-linux-x86_64-py312",
		"sm120-cu124-linux-x86_64-py312",
		"cpu-linux-x86_64-py312",
	}, map[string]any{"min_vram_mib": 8192})

	req := placementFor("demo:1", m, inv, "124", 512)
	if !req.GPUCompatible || len(req.GPUs) != 1 || req.GPUs[0] != "0" {
		t.Fatalf("single GPU placement = %+v", req)
	}
	if req.CPUAdmitted {
		t.Fatalf("CPU should not be admitted while a GPU is available: %+v", req)
	}

	m = placementManifest(t, []string{
		"sm89-cu124-linux-x86_64-py312",
		"sm120-cu124-linux-x86_64-py312",
	}, map[string]any{"min_vram_mib": 8192, "gpu_count": 2})
	req = placementFor("demo:1", m, inv, "124", 512)
	if !req.GPUCompatible || len(req.GPUs) != 2 || req.GPUs[0] != "0" || req.GPUs[1] != "1" {
		t.Fatalf("multi GPU placement = %+v", req)
	}
}

func TestPlacementAllOrNothingGPUReservation(t *testing.T) {
	// The second GPU has only 4 GiB free: a 2-GPU model cannot be placed, and
	// the scheduler must not fall back to CPU while a GPU runtime exists.
	inv := twoGPUInventory(4 << 30)
	m := placementManifest(t, []string{
		"sm89-cu124-linux-x86_64-py312",
		"sm120-cu124-linux-x86_64-py312",
		"cpu-linux-x86_64-py312",
	}, map[string]any{"min_vram_mib": 8192, "gpu_count": 2})

	req := placementFor("demo:1", m, inv, "124", 512)
	if !req.GPUCompatible || len(req.GPUs) != 0 {
		t.Fatalf("placement = %+v", req)
	}
	if req.Reason != reasonResourceExhausted {
		t.Fatalf("reason = %q", req.Reason)
	}
	if !req.CPUCompatible || req.CPUAdmitted {
		t.Fatalf("CPU must stay a compatibility fact but not a fallback: %+v", req)
	}
}

func TestPlacementCPUFallbackOnlyWithoutGPURuntime(t *testing.T) {
	inv := twoGPUInventory(28 << 30)
	m := placementManifest(t, []string{"cpu-linux-x86_64-py312"}, nil)
	req := placementFor("demo:1", m, inv, "124", 512)
	if req.GPUCompatible || !req.CPUCompatible || !req.CPUAdmitted {
		t.Fatalf("CPU-only placement = %+v", req)
	}

	m = placementManifest(t, []string{"sm86-cu124-linux-x86_64-py312"}, nil)
	req = placementFor("demo:1", m, inv, "124", 512)
	if req.GPUCompatible || req.CPUCompatible {
		t.Fatalf("incompatible runtime placement = %+v", req)
	}
	if req.Reason != reasonNoCompatibleRuntime {
		t.Fatalf("reason = %q", req.Reason)
	}
}

func TestPlacementCPURAMAdmission(t *testing.T) {
	inv := inventoryFrom(nil, "")
	m := placementManifest(t, []string{"cpu-linux-x86_64-py312"}, map[string]any{"min_ram_mib": 1 << 20})
	req := placementFor("demo:1", m, inv, "", 512)
	if !req.CPUCompatible || req.CPUAdmitted {
		t.Fatalf("CPU RAM admission = %+v", req)
	}
	if req.Reason != reasonResourceExhausted {
		t.Fatalf("reason = %q", req.Reason)
	}
}

func TestDevicesEndpoint(t *testing.T) {
	gpus := []gpu.Device{
		{Index: 0, Name: "RTX 4090", MemoryTotal: 24 << 30, MemoryFree: 20 << 30, ComputeCap: "8.9", DriverVersion: "555.1"},
		{Index: 1, Name: "RTX 5090", MemoryTotal: 32 << 30, MemoryFree: 28 << 30, ComputeCap: "12.0", DriverVersion: "555.1"},
	}
	s := &Server{
		GPU:             func(context.Context) ([]gpu.Device, error) { return gpus, nil },
		VRAMHeadroomMiB: 1024,
	}
	rec, body := call(t, s.Handler(), http.MethodGet, "/api/v1/devices", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("devices = %d: %s", rec.Code, rec.Body.String())
	}
	devices, ok := body["devices"].([]any)
	if !ok || len(devices) != 3 {
		t.Fatalf("devices = %v", body["devices"])
	}
	if body["vram_headroom_mib"].(float64) != 1024 {
		t.Fatalf("headroom = %v", body["vram_headroom_mib"])
	}
	first, _ := devices[0].(map[string]any)
	if first["kind"] != "cuda" || first["id"] != "0" || first["compute_cap"] != "8.9" {
		t.Fatalf("first device = %v", first)
	}
	cpu, _ := devices[2].(map[string]any)
	if cpu["kind"] != "cpu" || cpu["id"] != "cpu" {
		t.Fatalf("cpu device = %v", cpu)
	}
}

type serveSource struct{}

func (serveSource) Models(context.Context) ([]host.Model, error) {
	return []host.Model{{Ref: "demo:1", CacheKey: "demo/1", Serve: true}}, nil
}
func (serveSource) Storage(context.Context) ([]host.Area, error) { return nil, nil }

func TestSchedulerEndpointReportsPlacement(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	envs := []string{"sm89-cu124-linux-x86_64-py312", "cpu-linux-x86_64-py312"}
	root := filepath.Join(paths.Bundles(), "demo", "1")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	blob, err := json.Marshal(placementManifestData(envs, map[string]any{"min_vram_mib": 8192}))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, flashhub.ManifestPath), blob, 0o644); err != nil {
		t.Fatal(err)
	}

	s := &Server{
		Source: serveSource{},
		GPU: func(context.Context) ([]gpu.Device, error) {
			return []gpu.Device{{Index: 0, Name: "RTX 4090", MemoryTotal: 24 << 30, MemoryFree: 20 << 30, ComputeCap: "8.9"}}, nil
		},
	}
	rec, body := call(t, s.Handler(), http.MethodGet, "/api/v1/scheduler", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("scheduler = %d: %s", rec.Code, rec.Body.String())
	}
	reqs, ok := body["requirements"].([]any)
	if !ok || len(reqs) != 1 {
		t.Fatalf("requirements = %v", body["requirements"])
	}
	req, _ := reqs[0].(map[string]any)
	if req["ref"] != "demo:1" || req["gpu_compatible"] != true {
		t.Fatalf("requirement = %v", req)
	}
}
