package server

import (
	"encoding/json"
	"os"
)

// Config is the on-disk flashserver configuration written by flashserver-setup.
type Config struct {
	Addr           string `json:"addr"`
	Token          string `json:"token,omitempty"`
	FlashcliBin    string `json:"flashcli_bin,omitempty"`
	PublicHost     string `json:"public_host,omitempty"`
	ServeHost      string `json:"serve_host,omitempty"`
	LogDir         string `json:"log_dir,omitempty"`
	MaxLoaded      int    `json:"max_loaded,omitempty"`
	MinFreeVRAMMiB int64  `json:"min_free_vram_mib,omitempty"`
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
	if s.Manager != nil {
		s.Manager = NewManagerWithOptions(FlashcliLauncher{
			Bin: cfg.FlashcliBin, Host: cfg.ServeHost, PublicHost: cfg.PublicHost, LogDir: cfg.LogDir,
		}, ManagerOptions{
			MaxLoaded:      cfg.MaxLoaded,
			MinFreeVRAMMiB: cfg.MinFreeVRAMMiB,
			GPU:            s.GPU,
		})
	}
	return s
}
