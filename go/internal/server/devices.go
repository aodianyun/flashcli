package server

import (
	"context"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/preflight"
)

// DeviceInfo is one schedulable device: an NVIDIA GPU or the CPU.
type DeviceInfo struct {
	Kind             string `json:"kind"`
	ID               string `json:"id"`
	Name             string `json:"name,omitempty"`
	MemoryTotalBytes int64  `json:"memory_total_bytes,omitempty"`
	MemoryUsedBytes  int64  `json:"memory_used_bytes,omitempty"`
	MemoryFreeBytes  int64  `json:"memory_free_bytes,omitempty"`
	ComputeCap       string `json:"compute_cap,omitempty"`
	DriverVersion    string `json:"driver_version,omitempty"`
	Cores            int    `json:"cores,omitempty"`
	Threads          int    `json:"threads,omitempty"`
}

// DeviceInventory is the WSL-visible device and memory picture. iGPU, AMD, and
// Windows-native backends are out of scope for this contract.
type DeviceInventory struct {
	Devices                []DeviceInfo `json:"devices"`
	GPUError               string       `json:"gpu_error,omitempty"`
	CUDATag                string       `json:"cuda_tag,omitempty"`
	CPUModel               string       `json:"cpu_model,omitempty"`
	MemoryTotalBytes       int64        `json:"memory_total_bytes,omitempty"`
	MemoryFreeBytes        int64        `json:"memory_free_bytes,omitempty"`
	MemoryUsedBytes        int64        `json:"memory_used_bytes,omitempty"`
	CgroupMemoryLimitBytes int64        `json:"cgroup_memory_limit_bytes,omitempty"`
	CgroupMemoryUsedBytes  int64        `json:"cgroup_memory_used_bytes,omitempty"`
	CgroupCPUCores         float64      `json:"cgroup_cpu_cores,omitempty"`
}

// ResourceRequirement is the placement answer for one cached serve bundle. It
// answers "can this ref run here, and on which devices?" without starting a
// process.
type ResourceRequirement struct {
	Ref           string   `json:"ref"`
	GPUCount      int      `json:"gpu_count"`
	MinVRAMMiB    int64    `json:"min_vram_mib"`
	MinRAMMiB     int64    `json:"min_ram_mib"`
	GPUCompatible bool     `json:"gpu_compatible"`
	GPUCells      []string `json:"gpu_cells,omitempty"`
	GPUs          []string `json:"gpus,omitempty"`
	CPUCompatible bool     `json:"cpu_compatible"`
	CPUAdmitted   bool     `json:"cpu_admitted"`
	Reason        string   `json:"reason,omitempty"`
}

const (
	reasonNoCompatibleRuntime = "no_compatible_runtime"
	reasonResourceExhausted   = "resource_exhausted"
)

// devicesResponse adds the configured headroom to the raw inventory.
type devicesResponse struct {
	DeviceInventory
	VRAMHeadroomMiB int64 `json:"vram_headroom_mib"`
}

// schedulerResponse is the scheduler-side view exposed at /api/v1/scheduler.
type schedulerResponse struct {
	Slots           map[string]int        `json:"slots"`
	Resident        []InstanceInfo        `json:"resident"`
	Queue           []string              `json:"queue"`
	Reservations    []ResidentInfo        `json:"reservations"`
	ActiveLeases    int                   `json:"active_leases"`
	Waiters         int                   `json:"waiters"`
	VRAMHeadroomMiB int64                 `json:"vram_headroom_mib"`
	Requirements    []ResourceRequirement `json:"requirements"`
}

func (s *Server) vramHeadroomMiB() int64 {
	if s.VRAMHeadroomMiB < 0 {
		return 0
	}
	if s.VRAMHeadroomMiB == 0 {
		return 512
	}
	return int64(s.VRAMHeadroomMiB)
}

// inventory probes the devices visible to WSL: NVIDIA dGPUs plus CPU/RAM and
// cgroup limits. A GPU probe failure is reported, not fatal: CPU remains usable.
func (s *Server) inventory(ctx context.Context) DeviceInventory {
	var devices []gpu.Device
	gpuErr := ""
	if s.GPU != nil {
		out, err := s.GPU(ctx)
		if err != nil {
			gpuErr = err.Error()
		} else {
			devices = out
		}
	}
	inv := inventoryFrom(devices, gpuErr)
	info := preflight.DetectGPU()
	if info != nil {
		inv.CUDATag = info.CudaTag
		for i := range inv.Devices {
			if inv.Devices[i].Kind == "cuda" && inv.Devices[i].ComputeCap == "" && inv.Devices[i].ID == "0" {
				inv.Devices[i].ComputeCap = dotSM(info.SM)
			}
		}
	}
	return inv
}

func inventoryFrom(devices []gpu.Device, gpuErr string) DeviceInventory {
	inv := DeviceInventory{GPUError: gpuErr}
	for _, d := range devices {
		inv.Devices = append(inv.Devices, DeviceInfo{
			Kind: "cuda", ID: strconv.Itoa(d.Index), Name: d.Name,
			MemoryTotalBytes: d.MemoryTotal, MemoryUsedBytes: d.MemoryUsed, MemoryFreeBytes: d.MemoryFree,
			ComputeCap: d.ComputeCap, DriverVersion: d.DriverVersion,
		})
	}

	model, threads, physical, _ := readCPUStatic()
	memTotal, memAvail, _, _ := readMemInfo()
	cgLimit, cgUsed := readCgroupMemory()
	cgCores := readCgroupCPUCores()

	total := int64(memTotal)
	available := int64(memAvail)
	if cgLimit > 0 && (total == 0 || cgLimit < total) {
		total = cgLimit
	}
	if cgLimit > 0 {
		cgFree := cgLimit - cgUsed
		if cgFree < 0 {
			cgFree = 0
		}
		if available == 0 || cgFree < available {
			available = cgFree
		}
	}
	if available > total && total > 0 {
		available = total
	}
	used := total - available
	if used < 0 {
		used = 0
	}
	inv.Devices = append(inv.Devices, DeviceInfo{
		Kind: "cpu", ID: "cpu", Name: model,
		MemoryTotalBytes: total, MemoryFreeBytes: available, MemoryUsedBytes: used,
		Cores: physical, Threads: threads,
	})
	inv.CPUModel = model
	inv.MemoryTotalBytes = total
	inv.MemoryFreeBytes = available
	inv.MemoryUsedBytes = used
	inv.CgroupMemoryLimitBytes = cgLimit
	inv.CgroupMemoryUsedBytes = cgUsed
	inv.CgroupCPUCores = cgCores
	return inv
}

// placementFor answers whether one bundle can run on this inventory. It never
// reserves anything; M3 adds live reservations and eviction.
func placementFor(refStr string, m *manifest.Manifest, inv DeviceInventory, cudaTag string, headroomMiB int64) ResourceRequirement {
	res := m.Resources()
	req := ResourceRequirement{
		Ref: refStr, GPUCount: res.GPUCount,
		MinVRAMMiB: res.MinVRAMMiB, MinRAMMiB: res.MinRAMMiB,
	}
	if req.GPUCount < 1 {
		req.GPUCount = 1
	}
	abi := m.PythonABIOrEmpty()
	needBytes := (res.MinVRAMMiB + headroomMiB) * 1024 * 1024

	var compatible []DeviceInfo
	for _, d := range inv.Devices {
		if d.Kind != "cuda" || d.ComputeCap == "" {
			continue
		}
		key := preflight.HostEnvKeyFor(strings.ReplaceAll(d.ComputeCap, ".", ""), cudaTag, abi)
		resolved, err := m.ResolveEnvKey(key)
		if err != nil || resolved == "" {
			continue
		}
		req.GPUCells = append(req.GPUCells, resolved)
		compatible = append(compatible, d)
	}
	req.GPUCompatible = len(compatible) > 0

	// CPU compatibility is a fact about the bundle, but CPU is admitted only
	// when no compatible GPU runtime exists.
	cpuKey := preflight.HostEnvKey(nil, abi)
	resolvedCPU, cpuErr := m.ResolveEnvKey(cpuKey)
	req.CPUCompatible = cpuErr == nil && resolvedCPU != ""

	if req.GPUCompatible {
		for _, d := range compatible {
			if d.MemoryFreeBytes < needBytes {
				continue
			}
			req.GPUs = append(req.GPUs, d.ID)
			if len(req.GPUs) == req.GPUCount {
				break
			}
		}
		if len(req.GPUs) < req.GPUCount {
			req.GPUs = nil
			req.Reason = reasonResourceExhausted
		}
		return req
	}

	// No compatible GPU runtime: CPU is the only placement candidate.
	if !req.CPUCompatible {
		req.Reason = reasonNoCompatibleRuntime
		return req
	}
	if res.MinRAMMiB > 0 {
		free := cpuFreeBytes(inv)
		if free < res.MinRAMMiB*1024*1024 {
			req.Reason = reasonResourceExhausted
			return req
		}
	}
	req.CPUAdmitted = true
	return req
}

func cpuFreeBytes(inv DeviceInventory) int64 {
	for _, d := range inv.Devices {
		if d.Kind == "cpu" {
			return d.MemoryFreeBytes
		}
	}
	return inv.MemoryFreeBytes
}

// applyCPUPolicy enforces cpu_fallback=disabled. Compatibility stays visible,
// but CPU cannot be admitted when no GPU runtime matches.
func applyCPUPolicy(req *ResourceRequirement, disabled bool) {
	if !disabled || req.GPUCompatible {
		return
	}
	req.CPUAdmitted = false
	if req.Reason == "" {
		req.Reason = reasonNoCompatibleRuntime
	}
}

// placementRequirements inspects cached serve bundles. Bundle read failures are
// skipped: this endpoint is telemetry, not admission.
func (s *Server) placementRequirements(ctx context.Context, inv DeviceInventory) []ResourceRequirement {
	out := make([]ResourceRequirement, 0)
	if s.Source == nil {
		return out
	}
	models, err := s.Source.Models(ctx)
	if err != nil {
		return out
	}
	headroom := s.vramHeadroomMiB()
	for _, model := range models {
		if !model.Serve || model.CacheKey == "" {
			continue
		}
		root := filepath.Join(paths.Bundles(), filepath.FromSlash(model.CacheKey))
		m, err := manifest.Load(root)
		if err != nil {
			continue
		}
		req := placementFor(model.Ref, m, inv, inv.CUDATag, headroom)
		applyCPUPolicy(&req, s.CPUFallback == "disabled")
		out = append(out, req)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Ref < out[j].Ref })
	return out
}

func (s *Server) devices(w http.ResponseWriter, r *http.Request) {
	inv := s.inventory(r.Context())
	writeJSON(w, http.StatusOK, devicesResponse{DeviceInventory: inv, VRAMHeadroomMiB: s.vramHeadroomMiB()})
}

func (s *Server) scheduler(w http.ResponseWriter, r *http.Request) {
	used, maxLoaded := 0, 0
	if s.Manager != nil {
		used, maxLoaded = s.Manager.Slots()
	}
	inv := s.inventory(r.Context())
	snap := SchedulerSnapshot{Reservations: []ResidentInfo{}, Queue: []string{}}
	if s.Scheduler != nil {
		snap = s.Scheduler.Snapshot()
	}
	writeJSON(w, http.StatusOK, schedulerResponse{
		Slots:           map[string]int{"used": used, "max": maxLoaded},
		Resident:        s.loaded(),
		Queue:           snap.Queue,
		Reservations:    snap.Reservations,
		ActiveLeases:    snap.ActiveLeases,
		Waiters:         snap.Waiters,
		VRAMHeadroomMiB: s.vramHeadroomMiB(),
		Requirements:    s.placementRequirements(r.Context(), inv),
	})
}

func dotSM(sm string) string {
	sm = strings.TrimSpace(sm)
	if len(sm) == 3 {
		return sm[:2] + "." + sm[2:]
	}
	if len(sm) == 2 {
		return sm[:1] + "." + sm[1:]
	}
	return sm
}

func readCgroupMemory() (limit, used int64) {
	if blob, err := os.ReadFile("/sys/fs/cgroup/memory.max"); err == nil {
		raw := strings.TrimSpace(string(blob))
		if raw != "" && raw != "max" {
			limit, _ = strconv.ParseInt(raw, 10, 64)
		}
		if blob, err := os.ReadFile("/sys/fs/cgroup/memory.current"); err == nil {
			used, _ = strconv.ParseInt(strings.TrimSpace(string(blob)), 10, 64)
		}
		return normalizeCgroupLimit(limit), used
	}
	if blob, err := os.ReadFile("/sys/fs/cgroup/memory/memory.limit_in_bytes"); err == nil {
		limit, _ = strconv.ParseInt(strings.TrimSpace(string(blob)), 10, 64)
	}
	if blob, err := os.ReadFile("/sys/fs/cgroup/memory/memory.usage_in_bytes"); err == nil {
		used, _ = strconv.ParseInt(strings.TrimSpace(string(blob)), 10, 64)
	}
	return normalizeCgroupLimit(limit), used
}

func normalizeCgroupLimit(v int64) int64 {
	if v <= 0 || v >= 1<<60 {
		return 0
	}
	return v
}

func readCgroupCPUCores() float64 {
	if blob, err := os.ReadFile("/sys/fs/cgroup/cpu.max"); err == nil {
		fields := strings.Fields(string(blob))
		if len(fields) >= 2 && fields[0] != "max" {
			quota, err1 := strconv.ParseFloat(fields[0], 64)
			period, err2 := strconv.ParseFloat(fields[1], 64)
			if err1 == nil && err2 == nil && quota > 0 && period > 0 {
				return quota / period
			}
		}
		return 0
	}
	quota, err1 := readInt64File("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
	period, err2 := readInt64File("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
	if err1 == nil && err2 == nil && quota > 0 && period > 0 {
		return float64(quota) / float64(period)
	}
	return 0
}

func readInt64File(path string) (int64, error) {
	blob, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	return strconv.ParseInt(strings.TrimSpace(string(blob)), 10, 64)
}
