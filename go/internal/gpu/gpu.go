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
}

// Probe queries nvidia-smi. It works on Linux, WSL2, and Windows hosts that
// expose nvidia-smi in PATH.
func Probe(ctx context.Context) ([]Device, error) {
	c, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	out, err := exec.CommandContext(c, nvidiaSMI(), "--query-gpu=index,name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits").Output()
	if err != nil {
		return nil, fmt.Errorf("nvidia-smi: %w", err)
	}
	return Parse(string(out))
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

// Parse parses nvidia-smi CSV output. Values are MiB and converted to bytes.
func Parse(out string) ([]Device, error) {
	var devices []Device
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		fields := strings.Split(line, ",")
		if len(fields) != 5 {
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
		devices = append(devices, Device{
			Index: index, Name: strings.TrimSpace(fields[1]),
			MemoryTotal: total, MemoryUsed: used, MemoryFree: free,
		})
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
