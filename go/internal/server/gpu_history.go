package server

import (
	"context"
	"net/http"
	"strconv"
	"time"

	"github.com/aodianyun/flashcli/go/internal/gpu"
)

// GpuSampleDevice is one device in a telemetry sample.
type GpuSampleDevice struct {
	Index           int      `json:"index"`
	UtilizationGPU  *int     `json:"utilization_gpu_pct,omitempty"`
	MemoryUsedBytes int64    `json:"memory_used_bytes"`
	TemperatureC    *int     `json:"temperature_c,omitempty"`
	PowerDrawW      *float64 `json:"power_draw_w,omitempty"`
}

// GpuSample is one point in the daemon's GPU telemetry ring.
type GpuSample struct {
	Time    time.Time         `json:"time"`
	Devices []GpuSampleDevice `json:"devices"`
}

const (
	gpuSampleInterval = 5 * time.Second
	gpuSampleMax      = 360 // 30 minutes at 5s
)

func (s *Server) startGPUHistory(ctx context.Context) {
	s.histOnce.Do(func() {
		go func() {
			ticker := time.NewTicker(gpuSampleInterval)
			defer ticker.Stop()
			s.sampleGPUHistory(ctx)
			for {
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
					s.sampleGPUHistory(ctx)
				}
			}
		}()
	})
}

func (s *Server) sampleGPUHistory(ctx context.Context) {
	if s.GPU == nil {
		return
	}
	devices, err := s.GPU(ctx)
	if err != nil {
		return
	}
	sample := GpuSample{Time: time.Now().UTC()}
	for _, d := range devices {
		sample.Devices = append(sample.Devices, GpuSampleDevice{
			Index: d.Index, UtilizationGPU: d.UtilizationGPU,
			MemoryUsedBytes: d.MemoryUsed, TemperatureC: d.TemperatureC, PowerDrawW: d.PowerDrawW,
		})
	}
	s.histMu.Lock()
	s.history = append(s.history, sample)
	if len(s.history) > gpuSampleMax {
		s.history = append([]GpuSample(nil), s.history[len(s.history)-gpuSampleMax:]...)
	}
	s.histMu.Unlock()
}

func (s *Server) gpuHistory(w http.ResponseWriter, r *http.Request) {
	seconds := 300
	if raw := r.URL.Query().Get("seconds"); raw != "" {
		if v, err := strconv.Atoi(raw); err == nil {
			seconds = v
		}
	}
	if seconds < 10 {
		seconds = 10
	}
	if seconds > 900 {
		seconds = 900
	}
	cutoff := time.Now().Add(-time.Duration(seconds) * time.Second)
	s.histMu.Lock()
	samples := make([]GpuSample, 0, len(s.history))
	for _, sample := range s.history {
		if sample.Time.After(cutoff) {
			samples = append(samples, sample)
		}
	}
	s.histMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"samples": samples})
}

// gpuProcesses is a thin wrapper so handlers can tolerate probe failures.
func gpuProcesses(ctx context.Context) []gpu.Process {
	procs, err := gpu.Processes(ctx)
	if err != nil || procs == nil {
		return []gpu.Process{}
	}
	return procs
}
