package server

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/aodianyun/flashcli/go/internal/modelrun"
	"github.com/aodianyun/flashcli/go/internal/paths"
)

// Config is the on-disk flashserver configuration written by flashserver-setup.
type Config struct {
	Addr            string `json:"addr"`
	Token           string `json:"token,omitempty"`
	FlashcliBin     string `json:"flashcli_bin,omitempty"`
	PublicHost      string `json:"public_host,omitempty"`
	ServeHost       string `json:"serve_host,omitempty"`
	LogDir          string `json:"log_dir,omitempty"`
	MaxLoaded       int    `json:"max_loaded,omitempty"`
	VRAMHeadroomMiB int    `json:"vram_headroom_mib,omitempty"`

	IdleStopSeconds          int    `json:"idle_stop_seconds,omitempty"`
	ResidentStartWaitSeconds int    `json:"resident_start_wait_seconds,omitempty"`
	QueueTimeoutSeconds      int    `json:"queue_timeout_seconds,omitempty"`
	QueueMax                 int    `json:"queue_max,omitempty"`
	AutoPull                 *bool  `json:"auto_pull,omitempty"`
	CPUFallback              string `json:"cpu_fallback,omitempty"`
}

// Validate fails fast on invalid configuration.
func (c Config) Validate() error {
	if c.MaxLoaded < 0 {
		return fmt.Errorf("max_loaded must be >= 0")
	}
	if c.VRAMHeadroomMiB < 0 {
		return fmt.Errorf("vram_headroom_mib must be >= 0")
	}
	if c.IdleStopSeconds < 0 {
		return fmt.Errorf("idle_stop_seconds must be >= 0")
	}
	if c.ResidentStartWaitSeconds < 0 {
		return fmt.Errorf("resident_start_wait_seconds must be >= 0")
	}
	if c.QueueTimeoutSeconds < 0 {
		return fmt.Errorf("queue_timeout_seconds must be >= 0")
	}
	if c.QueueMax < 0 {
		return fmt.Errorf("queue_max must be >= 0")
	}
	switch c.CPUFallback {
	case "", "no-gpu-runtime", "disabled":
	default:
		return fmt.Errorf(`cpu_fallback must be "no-gpu-runtime" or "disabled"`)
	}
	return nil
}

// LoadConfig reads a JSON config file.
func LoadConfig(path string) (Config, error) {
	blob, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	var cfg Config
	if err := json.Unmarshal(blob, &cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

// NewFromConfig builds a server from config.
func NewFromConfig(cfg Config) *Server {
	s := New(cfg.Addr)
	s.Token = cfg.Token
	if cfg.LogDir != "" {
		s.LogDir = cfg.LogDir
	}
	s.FlashcliBin = cfg.FlashcliBin
	s.ServeHost = cfg.ServeHost
	s.PublicHost = cfg.PublicHost
	s.VRAMHeadroomMiB = cfg.VRAMHeadroomMiB
	if s.Manager != nil {
		s.Manager = NewManagerWithOptions(modelrun.FlashcliLauncher{
			Bin: cfg.FlashcliBin, Host: cfg.ServeHost, PublicHost: cfg.PublicHost, LogDir: s.LogDir,
		}, ManagerOptions{
			MaxLoaded:     cfg.MaxLoaded,
			GPU:           s.GPU,
			ServeSettings: s.ServeSettings,
			StatePath:     filepath.Join(paths.Home(), "flashserver", "models.json"),
		})
	}
	applyRuntimeConfig(s, cfg)
	s.buildScheduler()
	return s
}

// applyRuntimeConfig copies scheduler/gateway configuration onto the server.
func applyRuntimeConfig(s *Server, cfg Config) {
	s.VRAMHeadroomMiB = cfg.VRAMHeadroomMiB
	if cfg.IdleStopSeconds > 0 {
		s.IdleStopSeconds = cfg.IdleStopSeconds
	}
	if cfg.ResidentStartWaitSeconds > 0 {
		s.ResidentStartWaitSeconds = cfg.ResidentStartWaitSeconds
	}
	if cfg.QueueTimeoutSeconds > 0 {
		s.QueueTimeoutSeconds = cfg.QueueTimeoutSeconds
	}
	if cfg.QueueMax > 0 {
		s.QueueMax = cfg.QueueMax
	}
	if cfg.AutoPull != nil {
		s.AutoPull = *cfg.AutoPull
	}
	if cfg.CPUFallback != "" {
		s.CPUFallback = cfg.CPUFallback
	}
}
