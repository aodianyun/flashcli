package apps

import (
	"context"
	"fmt"
	"io"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
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
	Stopper func(context.Context, string) (bool, error)
	// Claim registers this application as an owner of an already healthy
	// model so another app stopping it does not take it away.
	Claim func(context.Context, string) error
	// ConfirmSetup asks the local user before running a setup script. The daemon
	// leaves it nil (the client sends confirmed script keys); the CLI prompts.
	ConfirmSetup func(SetupScript) bool
	Now          func() time.Time
	StartTimeout time.Duration

	mu    sync.Mutex
	procs map[string]modelrun.ServeProcess
}

// New returns a service wired to the shared host/modelrun implementation.
func New(home string) *Service {
	logDir := filepath.Join(home, "logs", "serve")
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
	// SetupScripts lists the setup script keys the user confirmed for this run
	// (empty = run none). ClientHome is the caller's OS home, used to write the
	// application's real config when the daemon runs in WSL. SetupProvided
	// distinguishes an explicit empty selection from "no selection supplied".
	SetupScripts  []string
	ClientHome    string
	SetupProvided bool
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
	ctx = WithOwner(ctx, key)

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
	// A reinstall can point at new bundle versions. Stop models that are no
	// longer in the manifest so their slots/VRAM are released (caches stay).
	if found {
		keep := make(map[string]bool, len(refs))
		for _, ref := range refs {
			keep[ref] = true
		}
		for i := range existing.Models {
			old := existing.Models[i]
			if keep[old.Ref] {
				continue
			}
			fmt.Fprintf(out, "\nRemoving model %s (no longer in the manifest)\n", old.Ref)
			s.stopModel(ctx, &old)
		}
	}
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
			state.Install.Command = command
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
					state.Install.Command = command
					state.Install.Skipped = true
					res.InstallSkipped = true
					break
				case !opts.Confirm(command):
					fmt.Fprintln(out, "Install command declined.")
					state.Install.Command = command
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
		state.UpdatedAt = s.now().UTC().Format(time.RFC3339)
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
		state.SetupError = ""
		state.UpdatedAt = s.now().UTC().Format(time.RFC3339)
		s.save(&state)
		if err := s.startModels(ctx, &state, opts.KeepPartial); err != nil {
			if ctx.Err() != nil {
				// Interrupted by a shutdown; the next daemon start resumes the
				// start (the models are already prepared).
				state.State = StateStarting
				state.UpdatedAt = s.now().UTC().Format(time.RFC3339)
				s.save(&state)
				return res, err
			}
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

	if !opts.NoStart {
		s.applySetupScripts(ctx, key, &state, SetupOptions{
			Scripts:    opts.SetupScripts,
			ClientHome: opts.ClientHome,
			Provided:   opts.SetupProvided,
		}, m)
	}

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
	return s.StartWithSetup(ctx, key, keepPartial, SetupOptions{})
}

// StartWithSetup starts the app's models and then runs the confirmed setup
// scripts in manifest order (each run is confirmed by the caller).
func (s *Service) StartWithSetup(ctx context.Context, key string, keepPartial bool, setup SetupOptions) (AppState, error) {
	st, ok, err := s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	ctx = WithOwner(ctx, key)
	st.State = StateStarting
	st.Error = ""
	// A previous failure belongs to the previous run; do not show it while
	// this start is in progress (setup runs again once the models are ready).
	st.SetupError = ""
	st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
	s.save(&st)
	if err := s.startModels(ctx, &st, keepPartial); err != nil {
		if ctx.Err() != nil {
			// The daemon is shutting down (or the caller went away). Keep the
			// start intent so the next daemon start retries it instead of
			// showing a false "failed: context canceled".
			st.State = StateStarting
			st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
			s.save(&st)
			return st, err
		}
		st.State = StateFailed
		st.Error = err.Error()
		st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
		s.save(&st)
		return st, err
	}
	st.State = StateReady
	st.Error = ""
	st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
	st.Connection = connectionFor(key, st.Version, st.Models)
	s.save(&st)
	s.applySetupScripts(ctx, key, &st, setup, nil)
	return st, nil
}

// applySetupScripts runs setup scripts after a successful model start. For the
// CLI, ConfirmSetup prompts for each manifest script; the daemon passes the
// already-confirmed keys. A failure is logged and stops the remaining scripts.
func (s *Service) applySetupScripts(ctx context.Context, key string, st *AppState, setup SetupOptions, m *Manifest) {
	// A restore (no explicit selection; the daemon has no terminal) replays the
	// pinned definitions from the last confirmed run. The scripts need the new
	// {base_url}/{model}/{api_key}, which only exist now that the models are
	// ready; no manifest fetch is needed, so a daemon restart works offline.
	if !setup.Provided && s.ConfirmSetup == nil && len(st.SetupPlan) > 0 {
		st.SetupError = ""
		if _, err := s.runSetupScripts(ctx, st.SetupPlan, st, st.SetupClientHome); err != nil {
			st.SetupError = setupFailure(ctx, err)
		}
		s.save(st)
		return
	}

	if m == nil && (setup.Provided || len(st.SetupScripts) > 0 || s.ConfirmSetup != nil) {
		fetched, err := s.manifestFor(ctx, key)
		if err != nil {
			if (setup.Provided && len(setup.Scripts) > 0) || len(st.SetupScripts) > 0 {
				fmt.Fprintf(s.out(), "setup skipped: %v\n", err)
				st.SetupError = setupFailure(ctx, err)
				s.save(st)
			}
			return
		}
		m = fetched
	}
	if m == nil {
		return
	}
	if len(m.Setup.Scripts) == 0 {
		if setup.Provided || len(st.SetupScripts) > 0 {
			st.SetupScripts = nil
			st.SetupPlan = nil
			s.save(st)
		}
		return
	}
	if !setup.Provided {
		if s.ConfirmSetup != nil {
			setup.Provided = true
			setup.Scripts = nil
			for _, script := range m.Setup.Scripts {
				if s.ConfirmSetup(script) {
					setup.Scripts = append(setup.Scripts, script.Key)
				}
			}
		} else {
			// Legacy state without pinned definitions: select the saved keys.
			setup.Provided = true
			setup.Scripts = append([]string(nil), st.SetupScripts...)
			setup.ClientHome = st.SetupClientHome
		}
	}
	// Pin the confirmed definitions in manifest order so a later restore can
	// run them without fetching the manifest again.
	confirmed := make(map[string]bool, len(setup.Scripts))
	for _, key := range setup.Scripts {
		confirmed[key] = true
	}
	selected := make([]SetupScript, 0, len(setup.Scripts))
	keys := make([]string, 0, len(setup.Scripts))
	for _, script := range m.Setup.Scripts {
		if confirmed[script.Key] {
			selected = append(selected, script)
			keys = append(keys, script.Key)
		}
	}
	st.SetupScripts = keys
	st.SetupPlan = selected
	if setup.ClientHome != "" {
		st.SetupClientHome = setup.ClientHome
	}
	st.SetupError = ""
	if len(selected) > 0 {
		if _, err := s.runSetupScripts(ctx, selected, st, setup.ClientHome); err != nil {
			st.SetupError = setupFailure(ctx, err)
		}
	}
	s.save(st)
}

// setupFailure keeps a real script/fetch failure but drops an interruption
// caused by a daemon shutdown; the next start/replay retries and a stale
// "context canceled" must not be shown as a configuration failure.
func setupFailure(ctx context.Context, err error) string {
	if ctx.Err() != nil {
		return ""
	}
	return err.Error()
}

func (s *Service) manifestFor(ctx context.Context, key string) (*Manifest, error) {
	ref, err := flashhub.ParseAppRef(key)
	if err != nil {
		return nil, err
	}
	raw, err := s.Fetch(ctx, ref)
	if err != nil {
		return nil, err
	}
	return Parse(raw)
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
	ctx = WithOwner(ctx, key)
	st.State = StateStopping
	st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
	s.save(&st)
	for i := range st.Models {
		s.stopModel(ctx, &st.Models[i])
	}
	st.State = StateStopped
	st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
	st.Connection = connectionFor(key, st.Version, st.Models)
	s.save(&st)
	return st, nil
}

// Status returns the stored state with live health annotations.
//
// The recorded state is reconciled with reality: after a daemon restart (or a
// crash/manual kill) an app can be stored as ready while its model process is
// gone. Reporting it as ready would disable 启动 and advertise a dead endpoint,
// so a ready app with no healthy model becomes stopped, and a partially healthy
// app becomes failed.
func (s *Service) Status(ctx context.Context, key string) (AppState, error) {
	st, ok, err := s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	changed := false
	now := s.now().UTC().Format(time.RFC3339)
	// A transitional state left behind by an interrupted run would keep the
	// UI's actions disabled forever. A live start/stop keeps it while the
	// operation is within its timeout; only an old one is reported as failed.
	if isTransitional(st.State) && s.transitionExpired(&st) {
		st.State = StateFailed
		if st.Error == "" {
			st.Error = "previous operation was interrupted"
		}
		changed = true
	}
	healthy, recorded := 0, 0
	for i := range st.Models {
		mdl := &st.Models[i]
		if mdl.Endpoint == "" {
			// Prepared but not started (install --no-start / start=false):
			// Prepared describes the weights cache, not liveness.
			continue
		}
		recorded++
		if endpointHealthy(ctx, mdl.Endpoint) {
			healthy++
			continue
		}
		// The recorded process is gone (daemon restart, crash, manual kill).
		// Drop the stale pid/endpoint so a later Stop cannot signal an
		// unrelated process and the connection info is not advertised.
		mdl.PID, mdl.Endpoint = 0, ""
		changed = true
	}
	if recorded > 0 {
		switch st.State {
		case StateReady:
			if healthy == 0 {
				st.State = StateStopped
				st.Error = ""
				changed = true
			} else if healthy < recorded {
				st.State = StateFailed
				st.Error = "some models are not running"
				changed = true
			}
		case StateFailed:
			if healthy == recorded {
				st.State = StateReady
				st.Error = ""
				changed = true
			}
		}
	}
	// Endpoints change on every start (the Manager picks the port), so the
	// advertised connection must never be a port from a previous run.
	if conn := connectionFor(key, st.Version, st.Models); !reflect.DeepEqual(conn, st.Connection) {
		st.Connection = conn
		changed = true
	}
	if changed {
		st.UpdatedAt = now
		s.save(&st)
	}
	return st, nil
}

// isTransitional reports whether an operation is in progress.
func isTransitional(state string) bool {
	switch state {
	case StateInstalling, StatePreparing, StateStarting, StateStopping:
		return true
	}
	return false
}

// transitionExpired reports whether a transitional state is old enough to be an
// interrupted run. startTimeout bounds one model start; allow several models
// and some slack before declaring the operation dead.
func (s *Service) transitionExpired(st *AppState) bool {
	if st.UpdatedAt == "" {
		return true
	}
	t, err := time.Parse(time.RFC3339, st.UpdatedAt)
	if err != nil {
		return true
	}
	limit := s.startTimeout() * 2
	if limit < 10*time.Minute {
		limit = 10 * time.Minute
	}
	return s.now().Sub(t) > limit
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
	ctx = WithOwner(ctx, key)
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
	return filepath.Join(s.LogDir, modelrun.LogName(ref))
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
			// Reusing another app's instance still makes this app an owner;
			// otherwise stopping the other app would unload it underneath us.
			if s.Claim != nil {
				if err := s.Claim(ctx, mdl.Ref); err != nil {
					return fail(fmt.Errorf("claim %s: %w", mdl.Ref, err))
				}
			}
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
		fmt.Fprintf(s.out(), "starting %s ...\n", mdl.Ref)
		proc, err := launcher.StartWithOptions(ctx, mdl.Ref, modelrun.LoadOptions{Port: port})
		if err != nil {
			return fail(fmt.Errorf("start %s: %w", mdl.Ref, err))
		}
		started = append(started, mdl)
		fmt.Fprintf(s.out(), "waiting for %s to become ready ...\n", mdl.Ref)
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
	return modelrun.WaitHealthy(ctx, proc, timeout, nil)
}

func (s *Service) stopModel(ctx context.Context, m *ModelState) {
	fmt.Fprintf(s.out(), "stopping %s ...\n", m.Ref)
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
