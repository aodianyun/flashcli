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
}

// Validate fails fast on invalid configuration.
func (c Config) Validate() error {
	if c.MaxLoaded < 0 {
		return fmt.Errorf("max_loaded must be >= 0")
	}
	if c.VRAMHeadroomMiB < 0 {
		return fmt.Errorf("vram_headroom_mib must be >= 0")
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
	return s
}
