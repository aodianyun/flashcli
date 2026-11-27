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

func TestConfigDefaultMaxLoadedIsUnlimited(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	cfg := Config{Addr: "127.0.0.1:8790"}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("default config rejected: %v", err)
	}
	s := NewFromConfig(cfg)
	if s.Manager == nil || s.Scheduler == nil {
		t.Fatal("manager/scheduler not built")
	}
	if s.Manager.opts.MaxLoaded != 0 {
		t.Fatalf("manager max_loaded = %d, want 0 (unlimited)", s.Manager.opts.MaxLoaded)
	}
	if s.Scheduler.opts.MaxLoaded != 0 {
		t.Fatalf("scheduler max_loaded = %d, want 0 (unlimited)", s.Scheduler.opts.MaxLoaded)
	}
	if used, max := s.Manager.Slots(); used != 0 || max != 0 {
		t.Fatalf("slots = %d/%d, want 0/0", used, max)
	}
	if m := NewManager(nil); m.opts.MaxLoaded != 0 {
		t.Fatalf("NewManager default max_loaded = %d, want 0", m.opts.MaxLoaded)
	}

	// An explicit positive limit is still honored.
	limited := NewFromConfig(Config{Addr: "127.0.0.1:8790", MaxLoaded: 2})
	if limited.Manager.opts.MaxLoaded != 2 || limited.Scheduler.opts.MaxLoaded != 2 {
		t.Fatalf("configured limit = manager %d scheduler %d, want 2",
			limited.Manager.opts.MaxLoaded, limited.Scheduler.opts.MaxLoaded)
	}
}
