package apps

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
)

// Launcher starts one model serve process (modelrun by default, fake in tests).
type Launcher interface {
	StartWithOptions(context.Context, string, modelrun.LoadOptions) (modelrun.ServeProcess, error)
}

// Service implements app install and lifecycle for one host.
type Service struct {
	Home       string
	Bin        string
	Host       string
	PublicHost string
	LogDir     string
	Out        io.Writer
	// Stdin is given to install commands. The CLI passes its own stdin so a
	// script may prompt; the daemon leaves it nil (child gets the null device)
	// so an unattended install can never block on input.
	Stdin    io.Reader
	Registry *Registry
	Launcher Launcher
	Prepare  func(context.Context, string) error
	Fetch    func(context.Context, flashhub.AppRef) ([]byte, error)
	// Stopper stops a model that this service instance did not start (for
	// example after a daemon restart or a shared Manager). It reports whether
	// the reference was handled; false falls back to the recorded PID.
	Stopper      func(context.Context, string) (bool, error)
	Now          func() time.Time
	StartTimeout time.Duration

	mu    sync.Mutex
	procs map[string]modelrun.ServeProcess
}

// New returns a service wired to the shared host/modelrun implementation.
func New(home string) *Service {
	logDir := filepath.Join(home, "flashserver", "logs", "serve")
	svc := &Service{
		Home:         home,
		Host:         "127.0.0.1",
		LogDir:       logDir,
		Out:          io.Discard,
		Registry:     NewRegistry(home),
		Now:          time.Now,
		StartTimeout: 120 * time.Second,
	}
	svc.Launcher = modelrun.FlashcliLauncher{LogDir: logDir}
	svc.Fetch = func(ctx context.Context, ref flashhub.AppRef) ([]byte, error) {
		return flashhub.NewClient().FetchAppManifest(ctx, ref)
	}
	svc.Prepare = func(ctx context.Context, ref string) error {
		_, err := host.Pull(ctx, ref, host.PullOptions{Progress: func(ev host.PullEvent) {
			if svc.Out != nil {
				fmt.Fprintf(svc.Out, "  %-8s %s\n", ev.Phase, ev.Message)
			}
		}})
		return err
	}
	return svc
}

// InstallOptions controls `app install`.
type InstallOptions struct {
	Yes         bool
	DryRun      bool
	Force       bool
	NoInstall   bool
	NoModel     bool
	NoStart     bool
	KeepPartial bool
	Bundles     []string
	// Confirm is asked before executing a shell install command. Nil means
	// "skip unless Yes".
	Confirm func(command string) bool
	// NonInteractive is set when stdin is not a terminal: without Yes there is
	// no way to ask, so the command is skipped.
	NonInteractive bool
	// OS/Arch override the platform used for the application check and for
	// picking the install command. The desktop client passes its own platform:
	// the application runs there even though the daemon runs in WSL.
	OS, Arch string
	// ScriptHandled records that the caller already executed the platform
	// install command on its own platform; the host only records it.
	ScriptHandled bool
}

// InstallResult describes what an install run did.
type InstallResult struct {
	State          AppState
	InstallRan     bool
	InstallSkipped bool
	AlreadyReady   bool
}

func (s *Service) setProc(ref string, proc modelrun.ServeProcess) {
	s.mu.Lock()
	if s.procs == nil {
		s.procs = map[string]modelrun.ServeProcess{}
	}
	s.procs[ref] = proc
	s.mu.Unlock()
}

func (s *Service) takeProc(ref string) modelrun.ServeProcess {
	s.mu.Lock()
	defer s.mu.Unlock()
	proc := s.procs[ref]
	delete(s.procs, ref)
	return proc
}

// installMu serializes installs in this process: preparing and starting two
// applications at once would fight over disk, ports and GPU memory.
var installMu sync.Mutex

// Install runs the flow from docs/application_install_plan.md.
func (s *Service) Install(ctx context.Context, rawRef string, opts InstallOptions) (InstallResult, error) {
	installMu.Lock()
	defer installMu.Unlock()
	ref, err := flashhub.ParseAppRef(rawRef)
	if err != nil {
		return InstallResult{}, err
	}
	raw, err := s.Fetch(ctx, ref)
	if err != nil {
		return InstallResult{}, err
	}
	m, err := Parse(raw)
	if err != nil {
		return InstallResult{}, err
	}
	if ref.Name != "" && !strings.EqualFold(ref.Name, m.Name) {
		return InstallResult{}, fmt.Errorf("application ref %q does not match manifest name %q", ref.String(), m.Name)
	}
	if ref.Version != "" && ref.Version != m.Version {
		return InstallResult{}, fmt.Errorf("application ref %q does not match manifest version %q", ref.String(), m.Version)
	}
	ref.Version = m.Version
	key := ref.String()

	goos, goarch := runtimeGOOS(), runtimeGOARCH()
	if opts.OS != "" {
		goos = opts.OS
	}
	if opts.Arch != "" {
		goarch = opts.Arch
	}
	if !Supported(m, goos, goarch) {
		return InstallResult{}, fmt.Errorf("application %s %s does not support %s/%s", key, m.Version, goos, goarch)
	}
	keyName, command, hasCommand := PlatformCommand(m, goos, goarch)
	refs := DefaultBundles(m, opts.Bundles)

	out := s.out()
	fmt.Fprintf(out, "Application: %s %s\n", m.DisplayName, m.Version)
	fmt.Fprintf(out, "Platform:    %s/%s (supported)\n", goos, goarch)
	if hasCommand {
		fmt.Fprintf(out, "Install:     [%s] %s\n", keyName, command)
	} else {
		fmt.Fprintln(out, "Install:     (none for this platform)")
	}
	fmt.Fprintf(out, "Models:      %s\n", strings.Join(refs, ", "))
	if opts.DryRun {
		fmt.Fprintln(out, "\nDRY RUN: nothing installed.")
		return InstallResult{}, nil
	}

	existing, found, err := s.Registry.Get(key)
	if err != nil {
		return InstallResult{}, err
	}
	if found && existing.State == StateReady && !opts.Force {
		fmt.Fprintf(out, "\n%s %s is already installed and ready (use --force to re-run).\n", key, m.Version)
		return InstallResult{State: existing, AlreadyReady: true}, nil
	}

	state := existing
	state.Key = key
	state.Version = m.Version
	state.State = StatePlanned
	state.Models = planModels(refs, existing.Models)
	s.save(&state)

	res := InstallResult{}
	if !opts.NoInstall && hasCommand {
		switch {
		case opts.ScriptHandled:
			// The caller installed the application on its own platform (the
			// desktop client downloads/runs a Windows installer; models stay in
			// WSL). Record it and never execute anything here.
			fmt.Fprintf(out, "\nInstall command already handled by the client: %s\n", command)
			state.Install = InstallRecord{Command: command, Executed: true}
			res.InstallRan = true
		case IsURL(command):
			fmt.Fprintf(out, "\nDownload page: %s\n", command)
			fmt.Fprintln(out, "Open it in a browser to install the application (flashcli does not auto-download).")
			state.Install.Skipped = true
			res.InstallSkipped = true
		default:
			// Without --yes, ask interactively. Only when there is no terminal
			// (no way to confirm) is the command skipped.
			run := opts.Yes
			if !run {
				switch {
				case opts.NonInteractive || opts.Confirm == nil:
					fmt.Fprintln(out, "Install command skipped: no interactive terminal to confirm (use --yes to run it).")
					state.Install.Skipped = true
					res.InstallSkipped = true
					break
				case !opts.Confirm(command):
					fmt.Fprintln(out, "Install command declined.")
					state.Install.Skipped = true
					res.InstallSkipped = true
					break
				default:
					run = true
				}
			}
			if !run {
				break
			}
			fmt.Fprintf(out, "\n$ %s\n", command)
			if err := s.runCommand(ctx, command); err != nil {
				state.State = StateFailed
				state.Error = err.Error()
				s.save(&state)
				return res, fmt.Errorf("install command failed: %w", err)
			}
			state.Install = InstallRecord{Command: command, Executed: true}
			res.InstallRan = true
		}
		s.save(&state)
	}

	if !opts.NoModel {
		state.State = StatePreparing
		s.save(&state)
		for i := range state.Models {
			mdl := &state.Models[i]
			if mdl.Prepared {
				continue
			}
			fmt.Fprintf(out, "\nPreparing model %s ...\n", mdl.Ref)
			if err := s.Prepare(ctx, mdl.Ref); err != nil {
				state.State = StateFailed
				state.Error = err.Error()
				s.save(&state)
				return res, fmt.Errorf("prepare model %s: %w", mdl.Ref, err)
			}
			mdl.Prepared = true
			s.save(&state)
		}
	}

	if !opts.NoStart {
		state.State = StateStarting
		s.save(&state)
		if err := s.startModels(ctx, &state, opts.KeepPartial); err != nil {
			state.State = StateFailed
			state.Error = err.Error()
			s.save(&state)
			return res, err
		}
	}

	now := s.now().UTC().Format(time.RFC3339)
	if state.InstalledAt == "" {
		state.InstalledAt = now
	}
	state.UpdatedAt = now
	state.State = StateReady
	state.Error = ""
	state.Connection = connectionFor(key, m.Version, state.Models)
	s.save(&state)

	fmt.Fprintf(out, "\nInstalled %s %s\n", key, m.Version)
	fmt.Fprintf(out, "Models:\n")
	for _, mdl := range state.Models {
		fmt.Fprintf(out, "  - %s  %s  (%s)\n", mdl.ID, mdl.Endpoint, mdl.Ref)
	}
	if state.Connection.BaseURL != "" {
		fmt.Fprintf(out, "Connection: %s (api_key=%s)\n", state.Connection.BaseURL, state.Connection.APIKey)
	}
	res.State = state
	return res, nil
}

// Start starts every prepared model of an installed app (idempotent).
func (s *Service) Start(ctx context.Context, key string, keepPartial bool) (AppState, error) {
	st, ok, err := s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	if err := s.startModels(ctx, &st, keepPartial); err != nil {
		st.State = StateFailed
		st.Error = err.Error()
		s.save(&st)
		return st, err
	}
	st.State = StateReady
	st.Error = ""
	st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
	s.save(&st)
	return st, nil
}

// Stop stops the app's models and marks it stopped.
func (s *Service) Stop(ctx context.Context, key string) (AppState, error) {
	st, ok, err := s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	for i := range st.Models {
		s.stopModel(ctx, &st.Models[i])
	}
	st.State = StateStopped
	st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
	s.save(&st)
	return st, nil
}

// Status returns the stored state with live health annotations.
func (s *Service) Status(ctx context.Context, key string) (AppState, error) {
	st, ok, err := s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	// A starting/stopping state left behind by an interrupted run (daemon
	// restart or crash) would keep the UI's actions disabled forever; report it
	// as failed so the user can start/stop again.
	if st.State == StateStarting || st.State == StatePreparing || st.State == StateInstalling {
		st.State = StateFailed
		if st.Error == "" {
			st.Error = "previous operation was interrupted"
		}
		s.save(&st)
	}
	for i := range st.Models {
		mdl := &st.Models[i]
		if mdl.Endpoint == "" {
			continue
		}
		if modelrun.HealthyEndpoint(ctx, mdl.Endpoint) == nil {
			mdl.Prepared = true
		}
	}
	return st, nil
}

// Uninstall stops the models and removes the app state; model caches stay
// unless purgeModels is set.
func (s *Service) Uninstall(ctx context.Context, key string, purgeModels bool) (AppState, error) {
	st, ok, err := s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	for i := range st.Models {
		s.stopModel(ctx, &st.Models[i])
	}
	if purgeModels {
		for _, mdl := range st.Models {
			if _, err := host.RemoveCachedRef(mdl.Ref); err != nil {
				return st, fmt.Errorf("remove model %s: %w", mdl.Ref, err)
			}
		}
	}
	if err := s.Registry.Update(func(m map[string]AppState) error {
		delete(m, key)
		return nil
	}); err != nil {
		return st, err
	}
	return st, nil
}

// ResolveKey maps a user ref to the installed registry key (latest version when
// the ref omits one).
func (s *Service) ResolveKey(ref flashhub.AppRef) (string, error) {
	apps, err := s.Registry.Load()
	if err != nil {
		return "", err
	}
	prefix := ref.Org + "/" + ref.Name + ":"
	if ref.Version != "" {
		key := prefix + ref.Version
		if _, ok := apps[key]; ok {
			return key, nil
		}
		return "", fmt.Errorf("application %s is not installed", key)
	}
	var keys []string
	for k := range apps {
		if strings.HasPrefix(k, prefix) {
			keys = append(keys, k)
		}
	}
	if len(keys) == 0 {
		return "", fmt.Errorf("application %s/%s is not installed", ref.Org, ref.Name)
	}
	sort.Strings(keys)
	return keys[len(keys)-1], nil
}

// ModelLogPath is the per-model serve log written by modelrun.
func (s *Service) ModelLogPath(ref string) string {
	name := strings.NewReplacer("/", "_", "\\", "_", ":", "_").Replace(ref) + ".log"
	return filepath.Join(s.LogDir, name)
}

func planModels(refs []string, existing []ModelState) []ModelState {
	byRef := map[string]ModelState{}
	for _, m := range existing {
		byRef[m.Ref] = m
	}
	out := make([]ModelState, 0, len(refs))
	for _, ref := range refs {
		st := byRef[ref]
		st.Ref = ref
		st.ID = ModelName(ref)
		out = append(out, st)
	}
	return out
}

func connectionFor(key, version string, models []ModelState) Connection {
	conn := Connection{APIKey: "local"}
	for _, m := range models {
		if m.Endpoint == "" {
			continue
		}
		conn.Models = append(conn.Models, m.ID)
		conn.ModelRefs = append(conn.ModelRefs, m.Ref)
		if conn.BaseURL == "" {
			conn.BaseURL = m.Endpoint + "/v1"
		}
	}
	_ = key
	_ = version
	return conn
}

func (s *Service) startModels(ctx context.Context, st *AppState, keepPartial bool) error {
	var started []*ModelState
	fail := func(err error) error {
		if !keepPartial {
			for _, m := range started {
				s.stopModel(ctx, m)
			}
		}
		return err
	}
	launcher := s.Launcher
	if launcher == nil {
		launcher = modelrun.FlashcliLauncher{Bin: s.Bin, Host: s.Host, PublicHost: s.PublicHost, LogDir: s.LogDir}
	}
	for i := range st.Models {
		mdl := &st.Models[i]
		if mdl.PID > 0 && mdl.Endpoint != "" && endpointHealthy(ctx, mdl.Endpoint) {
			fmt.Fprintf(s.out(), "  reuse %s at %s\n", mdl.ID, mdl.Endpoint)
			continue
		}
		port := mdl.Port
		if port <= 0 || !modelrun.PortAvailable(port) {
			var err error
			port, err = modelrun.FreePort()
			if err != nil {
				return fail(err)
			}
		}
		proc, err := launcher.StartWithOptions(ctx, mdl.Ref, modelrun.LoadOptions{Port: port})
		if err != nil {
			return fail(fmt.Errorf("start %s: %w", mdl.Ref, err))
		}
		started = append(started, mdl)
		if err := waitHealthy(ctx, proc, s.startTimeout()); err != nil {
			_ = proc.Stop(context.Background())
			return fail(fmt.Errorf("model %s did not become healthy: %w", mdl.Ref, err))
		}
		s.setProc(mdl.Ref, proc)
		mdl.Endpoint = proc.Endpoint()
		// A Manager-backed launcher picks its own port (it may honor the model
		// page's serve settings), so trust the endpoint over the requested port.
		if p := endpointPort(mdl.Endpoint); p > 0 {
			mdl.Port = p
		} else {
			mdl.Port = port
		}
		mdl.PID = proc.PID()
		mdl.Prepared = true
		s.save(st)
		fmt.Fprintf(s.out(), "  started %s at %s (pid %d)\n", mdl.ID, mdl.Endpoint, mdl.PID)
	}
	return nil
}

// endpointHealthy bounds the reuse probe so a stale endpoint cannot stall an
// install for the full health timeout.
func endpointHealthy(ctx context.Context, endpoint string) bool {
	probe, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	return modelrun.HealthyEndpoint(probe, endpoint) == nil
}

// endpointPort returns the port of an http endpoint, or 0 when unavailable.
func endpointPort(endpoint string) int {
	u, err := url.Parse(endpoint)
	if err != nil {
		return 0
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		return 0
	}
	return port
}

func waitHealthy(ctx context.Context, proc modelrun.ServeProcess, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for {
		if err := proc.Healthy(ctx); err == nil {
			return nil
		}
		if !proc.Running() {
			return errors.New("serve process exited")
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("timeout after %s", timeout)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(250 * time.Millisecond):
		}
	}
}

func (s *Service) stopModel(ctx context.Context, m *ModelState) {
	if proc := s.takeProc(m.Ref); proc != nil {
		_ = proc.Stop(ctx)
		m.PID, m.Endpoint = 0, ""
		return
	}
	if s.Stopper != nil {
		if handled, err := s.Stopper(ctx, m.Ref); handled {
			_ = err
			m.PID, m.Endpoint = 0, ""
			return
		}
	}
	if m.PID <= 0 {
		m.PID, m.Endpoint = 0, ""
		return
	}
	// Cross-process stop: the model was started by another flashcli process.
	if p, err := os.FindProcess(m.PID); err == nil {
		_ = p.Signal(os.Interrupt)
		time.Sleep(300 * time.Millisecond)
		_ = p.Kill()
	}
	m.PID, m.Endpoint = 0, ""
}

func (s *Service) runCommand(ctx context.Context, command string) error {
	name, args := ShellInvocation(runtimeGOOS(), command)
	cmd := execCommand(ctx, name, args...)
	cmd.Stdout = s.out()
	cmd.Stderr = s.out()
	cmd.Stdin = s.Stdin
	return cmd.Run()
}

func (s *Service) save(st *AppState) {
	_ = s.Registry.Update(func(m map[string]AppState) error {
		m[st.Key] = *st
		return nil
	})
}

func (s *Service) out() io.Writer {
	if s.Out == nil {
		return io.Discard
	}
	return s.Out
}

func (s *Service) now() time.Time {
	if s.Now == nil {
		return time.Now()
	}
	return s.Now()
}

func (s *Service) startTimeout() time.Duration {
	if s.StartTimeout <= 0 {
		return 120 * time.Second
	}
	return s.StartTimeout
}

func runtimeGOOS() string   { return runtime.GOOS }
func runtimeGOARCH() string { return runtime.GOARCH }
func execCommand(ctx context.Context, name string, args ...string) *exec.Cmd {
	return exec.CommandContext(ctx, name, args...)
}
