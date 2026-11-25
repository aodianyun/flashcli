package server

import (
	"strings"
	"testing"
)

func TestConfigValidation(t *testing.T) {
	valid := Config{MaxLoaded: 2, VRAMHeadroomMiB: 512, IdleStopSeconds: 600, QueueTimeoutSeconds: 30, QueueMax: 16, CPUFallback: "no-gpu-runtime"}
	if err := valid.Validate(); err != nil {
		t.Fatalf("valid config rejected: %v", err)
	}
	cases := []struct {
		name string
		cfg  Config
		want string
	}{
		{"max loaded", Config{MaxLoaded: -1}, "max_loaded"},
		{"headroom", Config{VRAMHeadroomMiB: -1}, "vram_headroom_mib"},
		{"idle", Config{IdleStopSeconds: -1}, "idle_stop_seconds"},
		{"start wait", Config{ResidentStartWaitSeconds: -1}, "resident_start_wait_seconds"},
		{"queue timeout", Config{QueueTimeoutSeconds: -1}, "queue_timeout_seconds"},
		{"queue max", Config{QueueMax: -1}, "queue_max"},
		{"cpu fallback", Config{CPUFallback: "always"}, "cpu_fallback"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.cfg.Validate()
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error = %v, want %q", err, tc.want)
			}
		})
	}
}

func TestBuildSchedulerUsesConfigDefaults(t *testing.T) {
	s := New("127.0.0.1:8790")
	if s.Scheduler == nil {
		t.Fatal("scheduler not built")
	}
	if s.CPUFallback != "no-gpu-runtime" || !s.AutoPull {
		t.Fatalf("defaults = cpu=%q auto_pull=%t", s.CPUFallback, s.AutoPull)
	}
}
