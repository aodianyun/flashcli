package apps

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// Connection is what an installed application needs to reach its model service.
type Connection struct {
	BaseURL   string   `json:"base_url"`
	APIKey    string   `json:"api_key"`
	Models    []string `json:"models"`
	ModelRefs []string `json:"model_refs"`
}

// InstallRecord captures what happened with the manifest install command.
type InstallRecord struct {
	Command  string `json:"command,omitempty"`
	Executed bool   `json:"executed"`
	Skipped  bool   `json:"skipped,omitempty"`
}

// ModelState is one prepared/running model of an application.
type ModelState struct {
	Ref      string `json:"ref"`
	ID       string `json:"id"`
	Port     int    `json:"port,omitempty"`
	PID      int    `json:"pid,omitempty"`
	Endpoint string `json:"endpoint,omitempty"`
	Prepared bool   `json:"prepared"`
}

// AppState is the persisted record for one installed application.
type AppState struct {
	Key         string        `json:"app"`
	Version     string        `json:"version"`
	State       string        `json:"state"`
	InstalledAt string        `json:"installed_at,omitempty"`
	UpdatedAt   string        `json:"updated_at,omitempty"`
	Install     InstallRecord `json:"install"`
	Models      []ModelState  `json:"models"`
	Connection  Connection    `json:"connection"`
	// SetupScripts/SetupPlan/SetupClientHome record the confirmed setup
	// selection (keys, the pinned definitions, and the client home) from the
	// last start/install. A daemon restart replays the plan automatically after
	// the restored models are ready, so the scripts receive the new connection
	// without fetching the manifest again.
	SetupScripts    []string      `json:"setup_scripts,omitempty"`
	SetupPlan       []SetupScript `json:"setup_plan,omitempty"`
	SetupClientHome string        `json:"setup_client_home,omitempty"`
	// SetupError keeps the last setup failure (the app itself stays ready).
	SetupError string `json:"setup_error,omitempty"`
	// LastLog keeps the tail of the last start output (copy/prepare/start and
	// setup lines). A daemon restore has no desktop job, so the detail pane
	// reads this to keep showing the log and a full-log entry.
	LastLog []string `json:"last_log,omitempty"`

	// Error keeps the last failure reason for `app status`.
	Error string `json:"error,omitempty"`
}

// Application states (see docs/application_install_plan.md).
const (
	StatePlanned    = "planned"
	StateInstalling = "installing"
	StatePreparing  = "preparing"
	StatePrepared   = "prepared"
	StateStarting   = "starting"
	StateReady      = "ready"
	StateStopped    = "stopped"
	StateStopping   = "stopping"
	StateFailed     = "failed"
)

// WasRunning reports whether an app was ready with models that had a recorded
// process. An app installed with start=false is ready but has no pid/endpoint,
// so it must not be restored after a daemon restart.
func WasRunning(st AppState) bool {
	if st.State != StateReady {
		return false
	}
	for _, mdl := range st.Models {
		if mdl.PID > 0 || mdl.Endpoint != "" {
			return true
		}
	}
	return false
}

// Registry persists application state in $FLASHCLI_HOME/flashserver/apps.json.
// The CLI and the daemon may both write it, so every update takes a
// cross-process lock file and writes atomically.
type Registry struct {
	Path string
}

// NewRegistry returns the shared app registry under home.
func NewRegistry(home string) *Registry {
	return &Registry{Path: filepath.Join(home, "flashserver", "apps.json")}
}

type registryFile struct {
	Apps map[string]AppState `json:"apps"`
}

// Load reads the registry (missing file = empty).
func (r *Registry) Load() (map[string]AppState, error) {
	blob, err := os.ReadFile(r.Path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]AppState{}, nil
	}
	if err != nil {
		return nil, err
	}
	var file registryFile
	if err := json.Unmarshal(blob, &file); err != nil {
		return nil, fmt.Errorf("parse %s: %w", r.Path, err)
	}
	if file.Apps == nil {
		file.Apps = map[string]AppState{}
	}
	return file.Apps, nil
}

// Update runs fn against the current state under a lock and persists the result.
func (r *Registry) Update(fn func(map[string]AppState) error) error {
	unlock, err := r.lock()
	if err != nil {
		return err
	}
	defer unlock()

	apps, err := r.Load()
	if err != nil {
		return err
	}
	if err := fn(apps); err != nil {
		return err
	}
	return r.save(apps)
}

func (r *Registry) lock() (func(), error) {
	if err := os.MkdirAll(filepath.Dir(r.Path), 0o755); err != nil {
		return nil, err
	}
	lockPath := r.Path + ".lock"
	deadline := time.Now().Add(10 * time.Second)
	for {
		f, err := os.OpenFile(lockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
		if err == nil {
			_ = f.Close()
			return func() { _ = os.Remove(lockPath) }, nil
		}
		if !errors.Is(err, os.ErrExist) {
			return nil, err
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("application registry is locked (%s); remove it if no other flashcli is running", lockPath)
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func (r *Registry) save(apps map[string]AppState) error {
	blob, err := json.MarshalIndent(registryFile{Apps: apps}, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(r.Path), 0o755); err != nil {
		return err
	}
	tmp := r.Path + ".tmp"
	if err := os.WriteFile(tmp, append(blob, '\n'), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, r.Path)
}

// Get returns one application state.
func (r *Registry) Get(key string) (AppState, bool, error) {
	apps, err := r.Load()
	if err != nil {
		return AppState{}, false, err
	}
	st, ok := apps[key]
	return st, ok, nil
}
