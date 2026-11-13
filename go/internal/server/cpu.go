package server

import (
	"os"
	"strconv"
	"strings"
)

type cpuCounters struct {
	total uint64
	idle  uint64
}

func readCPUCounterLines() ([]cpuCounters, error) {
	blob, err := os.ReadFile("/proc/stat")
	if err != nil {
		return nil, err
	}
	var out []cpuCounters
	for _, line := range strings.Split(string(blob), "\n") {
		if !strings.HasPrefix(line, "cpu") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 5 {
			continue
		}
		var total, idle uint64
		for i, raw := range fields[1:] {
			v, err := strconv.ParseUint(raw, 10, 64)
			if err != nil {
				continue
			}
			total += v
			if i == 3 || i == 4 { // idle, iowait
				idle += v
			}
		}
		out = append(out, cpuCounters{total: total, idle: idle})
	}
	return out, nil
}

func cpuUsageBetween(prev, cur []cpuCounters) (float64, []float64) {
	if len(cur) == 0 || len(prev) != len(cur) {
		return 0, nil
	}
	usageOf := func(a, b cpuCounters) float64 {
		total := float64(b.total) - float64(a.total)
		idle := float64(b.idle) - float64(a.idle)
		if total <= 0 {
			return 0
		}
		if idle < 0 {
			idle = 0
		}
		if idle > total {
			idle = total
		}
		return (total - idle) / total * 100
	}
	perCore := make([]float64, 0, len(cur)-1)
	for i := 1; i < len(cur); i++ {
		perCore = append(perCore, usageOf(prev[i], cur[i]))
	}
	return usageOf(prev[0], cur[0]), perCore
}

func readCPUStatic() (model string, threads, physical int, mhz float64) {
	blob, err := os.ReadFile("/proc/cpuinfo")
	if err != nil {
		return "", 0, 0, 0
	}
	var mhzSum float64
	var mhzN int
	for _, line := range strings.Split(string(blob), "\n") {
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.TrimSpace(value)
		switch key {
		case "model name":
			if model == "" {
				model = value
			}
		case "processor":
			threads++
		case "cpu cores":
			if physical == 0 {
				if v, err := strconv.Atoi(value); err == nil {
					physical = v
				}
			}
		case "cpu MHz":
			if v, err := strconv.ParseFloat(value, 64); err == nil {
				mhzSum += v
				mhzN++
			}
		}
	}
	if mhzN > 0 {
		mhz = mhzSum / float64(mhzN)
	}
	if physical == 0 {
		physical = threads
	}
	return model, threads, physical, mhz
}

func readMemInfo() (total, available, swapTotal, swapFree uint64) {
	blob, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return 0, 0, 0, 0
	}
	for _, line := range strings.Split(string(blob), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		v, err := strconv.ParseUint(fields[1], 10, 64)
		if err != nil {
			continue
		}
		v *= 1024 // kB
		switch fields[0] {
		case "MemTotal:":
			total = v
		case "MemAvailable:":
			available = v
		case "SwapTotal:":
			swapTotal = v
		case "SwapFree:":
			swapFree = v
		}
	}
	return total, available, swapTotal, swapFree
}

func readLoadAvg() (l1, l5, l15 float64) {
	blob, err := os.ReadFile("/proc/loadavg")
	if err != nil {
		return 0, 0, 0
	}
	fields := strings.Fields(string(blob))
	for i := 0; i < len(fields) && i < 3; i++ {
		v, err := strconv.ParseFloat(fields[i], 64)
		if err != nil {
			continue
		}
		switch i {
		case 0:
			l1 = v
		case 1:
			l5 = v
		case 2:
			l15 = v
		}
	}
	return l1, l5, l15
}

// pollCPU refreshes the usage snapshot from /proc/stat deltas.
func (s *Server) pollCPU() {
	cur, err := readCPUCounterLines()
	if err != nil || len(cur) == 0 {
		return
	}
	s.cpuMu.Lock()
	defer s.cpuMu.Unlock()
	if len(s.cpuPrev) == len(cur) {
		usage, cores := cpuUsageBetween(s.cpuPrev, cur)
		s.cpuUsage = usage
		s.cpuPerCore = cores
	}
	s.cpuPrev = cur
}

// cpuPayload returns the current CPU, memory and load snapshot.
func (s *Server) cpuPayload() map[string]any {
	model, threads, physical, mhz := readCPUStatic()
	memTotal, memAvail, swapTotal, swapFree := readMemInfo()
	l1, l5, l15 := readLoadAvg()
	s.cpuMu.Lock()
	usage := s.cpuUsage
	perCore := append([]float64(nil), s.cpuPerCore...)
	s.cpuMu.Unlock()
	var used uint64
	if memTotal >= memAvail {
		used = memTotal - memAvail
	}
	var swapUsed uint64
	if swapTotal >= swapFree {
		swapUsed = swapTotal - swapFree
	}
	return map[string]any{
		"model":               model,
		"threads":             threads,
		"cores":               physical,
		"mhz":                 mhz,
		"usage_pct":           usage,
		"per_core_pct":        perCore,
		"load1":               l1,
		"load5":               l5,
		"load15":              l15,
		"mem_total_bytes":     memTotal,
		"mem_used_bytes":      used,
		"mem_available_bytes": memAvail,
		"swap_total_bytes":    swapTotal,
		"swap_used_bytes":     swapUsed,
	}
}
