package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

// ModelServeSettings is the persisted per-model startup configuration.
// Empty Host/Options or zero Port means "use the server/bundle default".
type ModelServeSettings struct {
	Host    string            `json:"host,omitempty"`
	Port    int               `json:"port,omitempty"`
	Options map[string]string `json:"options,omitempty"`
}

type serveSettingsFile struct {
	Models map[string]ModelServeSettings `json:"models"`
}

type serveSettingsStore struct {
	mu     sync.Mutex
	path   string
	models map[string]ModelServeSettings
}

func defaultServeSettingsPath() string {
	return filepath.Join(paths.Home(), "flashserver", "serve-options.json")
}

func newServeSettingsStore(path string) *serveSettingsStore {
	if strings.TrimSpace(path) == "" {
		path = defaultServeSettingsPath()
	}
	s := &serveSettingsStore{path: path, models: map[string]ModelServeSettings{}}
	s.load()
	return s
}

func (s *serveSettingsStore) load() {
	blob, err := os.ReadFile(s.path)
	if err != nil {
		return
	}
	var file serveSettingsFile
	if err := json.Unmarshal(blob, &file); err != nil || file.Models == nil {
		return
	}
	s.models = file.Models
}

func (s *serveSettingsStore) Get(ref string) ModelServeSettings {
	s.mu.Lock()
	defer s.mu.Unlock()
	v := s.models[ref]
	if v.Options != nil {
		v.Options = cloneStringMap(v.Options)
	}
	return v
}

func (s *serveSettingsStore) Set(ref string, v ModelServeSettings) error {
	v.Host = strings.TrimSpace(v.Host)
	if v.Port < 0 || v.Port > 65535 {
		v.Port = 0
	}
	opts := make(map[string]string, len(v.Options))
	for name, value := range v.Options {
		value = strings.TrimSpace(value)
		if value != "" {
			opts[name] = value
		}
	}
	if len(opts) == 0 {
		opts = nil
	}
	v.Options = opts

	s.mu.Lock()
	defer s.mu.Unlock()
	if v.Host == "" && v.Port == 0 && len(v.Options) == 0 {
		delete(s.models, ref)
	} else {
		s.models[ref] = v
	}
	return s.saveLocked()
}

func (s *serveSettingsStore) Delete(ref string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.models, ref)
	return s.saveLocked()
}

func (s *serveSettingsStore) saveLocked() error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o755); err != nil {
		return err
	}
	blob, err := json.MarshalIndent(serveSettingsFile{Models: s.models}, "", "  ")
	if err != nil {
		return err
	}
	blob = append(blob, '\n')
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, blob, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, s.path)
}

func cloneStringMap(in map[string]string) map[string]string {
	out := make(map[string]string, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}
