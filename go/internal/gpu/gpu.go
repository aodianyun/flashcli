// Package gpu implements model-agnostic GPU inventory probing.
package gpu

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// Device is one NVIDIA GPU visible to the host.
type Device struct {
	Index       int    `json:"index"`
	Name        string `json:"name"`
	MemoryTotal int64  `json:"memory_total_bytes"`
	MemoryUsed  int64  `json:"memory_used_bytes"`
	MemoryFree  int64  `json:"memory_free_bytes"`

	UtilizationGPU    *int     `json:"utilization_gpu_pct,omitempty"`
	UtilizationMemory *int     `json:"utilization_memory_pct,omitempty"`
	TemperatureC      *int     `json:"temperature_c,omitempty"`
	PowerDrawW        *float64 `json:"power_draw_w,omitempty"`
	PowerLimitW       *float64 `json:"power_limit_w,omitempty"`
	FanSpeedPct       *int     `json:"fan_speed_pct,omitempty"`
	ClockGraphicsMHz  *int     `json:"clock_graphics_mhz,omitempty"`
	ClockMemoryMHz    *int     `json:"clock_memory_mhz,omitempty"`
	DriverVersion     string   `json:"driver_version,omitempty"`
	PersistenceMode   string   `json:"persistence_mode,omitempty"`
	ComputeMode       string   `json:"compute_mode,omitempty"`
	ComputeCap        string   `json:"compute_cap,omitempty"`
}

const queryFields = "index,name,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit,fan.speed,clocks.current.graphics,clocks.current.memory,driver_version,persistence_mode,compute_mode,compute_cap"

// Probe queries nvidia-smi. It works on Linux, WSL2, and Windows hosts that
// expose nvidia-smi in PATH.
func Probe(ctx context.Context) ([]Device, error) {
	c, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	out, err := exec.CommandContext(c, nvidiaSMI(), "--query-gpu="+queryFields, "--format=csv,noheader,nounits").Output()
	if err != nil {
		return nil, fmt.Errorf("nvidia-smi: %w", err)
	}
	return Parse(string(out))
}

// DriverVersion returns the installed NVIDIA driver version.
func DriverVersion(ctx context.Context) (string, error) {
	c, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	out, err := exec.CommandContext(c, nvidiaSMI(), "--query-gpu=driver_version", "--format=csv,noheader").Output()
	if err != nil {
		return "", err
	}
	line := strings.TrimSpace(strings.Split(string(out), "\n")[0])
	return line, nil
}

// CUDAVersion returns the CUDA version supported by the installed driver
// (from the nvidia-smi header, e.g. "13.1").
func CUDAVersion(ctx context.Context) (string, error) {
	c, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	out, err := exec.CommandContext(c, nvidiaSMI()).Output()
	if err != nil {
		return "", err
	}
	for _, line := range strings.Split(string(out), "\n") {
		idx := strings.Index(line, "CUDA Version:")
		if idx < 0 {
			continue
		}
		rest := strings.TrimSpace(line[idx+len("CUDA Version:"):])
		rest = strings.Trim(rest, "| ")
		if fields := strings.Fields(rest); len(fields) > 0 {
			return strings.TrimSpace(fields[0]), nil
		}
	}
	return "", nil
}

// nvidiaSMI resolves the probe binary. Services on WSL2 get a minimal PATH
// that omits /usr/lib/wsl/lib, so fall back to the standard driver mount.
func nvidiaSMI() string {
	if p, err := exec.LookPath("nvidia-smi"); err == nil {
		return p
	}
	for _, p := range []string{"/usr/lib/wsl/lib/nvidia-smi", `C:\Windows\System32\nvidia-smi.exe`} {
		if info, err := os.Stat(p); err == nil && !info.IsDir() {
			return p
		}
	}
	return "nvidia-smi"
}

// Process is one CUDA compute process reported by nvidia-smi.
type Process struct {
	PID         int    `json:"pid"`
	Name        string `json:"name"`
	MemoryBytes int64  `json:"memory_bytes"`
}

// Processes lists CUDA compute processes and their device memory usage.
func Processes(ctx context.Context) ([]Process, error) {
	c, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	out, err := exec.CommandContext(c, nvidiaSMI(), "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits").Output()
	if err != nil {
		return nil, fmt.Errorf("nvidia-smi processes: %w", err)
	}
	return ParseProcesses(string(out)), nil
}

// ParseProcesses parses `--query-compute-apps` output; malformed rows are skipped.
func ParseProcesses(out string) []Process {
	var procs []Process
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		fields := strings.SplitN(line, ",", 3)
		if len(fields) < 3 {
			continue
		}
		pid, err := strconv.Atoi(strings.TrimSpace(fields[0]))
		if err != nil {
			continue
		}
		memMiB, err := strconv.ParseInt(strings.TrimSpace(fields[2]), 10, 64)
		if err != nil {
			continue
		}
		procs = append(procs, Process{
			PID: pid, Name: strings.TrimSpace(fields[1]), MemoryBytes: memMiB * 1024 * 1024,
		})
	}
	return procs
}

// Parse parses nvidia-smi CSV output. Values are MiB and converted to bytes.
// The first five columns are required; the extended telemetry columns are
// optional so older/limited drivers still parse.
func Parse(out string) ([]Device, error) {
	var devices []Device
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		fields := strings.Split(line, ",")
		if len(fields) < 5 {
			return nil, fmt.Errorf("unexpected nvidia-smi line: %q", line)
		}
		index, err := strconv.Atoi(strings.TrimSpace(fields[0]))
		if err != nil {
			return nil, fmt.Errorf("gpu index: %w", err)
		}
		total, err := mib(fields[2])
		if err != nil {
			return nil, err
		}
		used, err := mib(fields[3])
		if err != nil {
			return nil, err
		}
		free, err := mib(fields[4])
		if err != nil {
			return nil, err
		}
		dev := Device{
			Index: index, Name: strings.TrimSpace(fields[1]),
			MemoryTotal: total, MemoryUsed: used, MemoryFree: free,
		}
		if len(fields) >= 16 {
			dev.UtilizationGPU = optInt(fields[5])
			dev.UtilizationMemory = optInt(fields[6])
			dev.TemperatureC = optInt(fields[7])
			dev.PowerDrawW = optFloat(fields[8])
			dev.PowerLimitW = optFloat(fields[9])
			dev.FanSpeedPct = optInt(fields[10])
			dev.ClockGraphicsMHz = optInt(fields[11])
			dev.ClockMemoryMHz = optInt(fields[12])
			dev.DriverVersion = optString(fields[13])
			dev.PersistenceMode = optString(fields[14])
			dev.ComputeMode = optString(fields[15])
		}
		if len(fields) >= 17 {
			dev.ComputeCap = optString(fields[16])
		}
		devices = append(devices, dev)
	}
	return devices, nil
}

func mib(raw string) (int64, error) {
	v, err := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
	if err != nil {
		return 0, fmt.Errorf("gpu memory %q: %w", raw, err)
	}
	return v * 1024 * 1024, nil
}

func optString(raw string) string {
	s := strings.TrimSpace(raw)
	if s == "" || strings.EqualFold(s, "N/A") || strings.HasPrefix(s, "[") {
		return ""
	}
	return s
}

func optInt(raw string) *int {
	if v, err := strconv.Atoi(strings.TrimSpace(raw)); err == nil {
		return &v
	}
	return nil
}

func optFloat(raw string) *float64 {
	if v, err := strconv.ParseFloat(strings.TrimSpace(raw), 64); err == nil {
		return &v
	}
	return nil
}
