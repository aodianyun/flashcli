package apps

import (
	"context"
	"fmt"
	"io"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
)

// Service implements app install and activation for one host.
type Service struct {
	Home   string
	LogDir string
	Out    io.Writer
	// Stdin is given to install commands. The CLI passes its own stdin so a
	// script may prompt; the daemon leaves it nil (child gets the null device)
	// so an unattended install can never block on input.
	Stdin    io.Reader
	Registry *Registry
	Prepare  func(context.Context, string) error
	Fetch    func(context.Context, flashhub.AppRef) ([]byte, error)
	// GatewayBaseURL is what setup scripts receive as {base_url}. Apps call the
	// flashserver OpenAI gateway; they never receive a model's child endpoint.
	// Empty uses http://127.0.0.1:8790/v1.
	GatewayBaseURL string
	// ConfirmSetup asks the local user before running a setup script. The daemon
	// leaves it nil (the client sends confirmed script keys); the CLI prompts.
	ConfirmSetup func(SetupScript) bool
	Now          func() time.Time
	StartTimeout time.Duration
}

// New returns a service wired to the shared host implementation.
func New(home string) *Service {
	logDir := filepath.Join(home, "logs", "serve")
	svc := &Service{
		Home:         home,
		LogDir:       logDir,
		Out:          io.Discard,
		Registry:     NewRegistry(home),
		Now:          time.Now,
		StartTimeout: 120 * time.Second,
	}
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

// appLocks serializes mutations of one application. Services are created per
// request/frontend, so the lock must live at package scope; otherwise a
// restore and a manual activation can run concurrently.
var appLocks sync.Map

func lockApp(key string) func() {
	v, _ := appLocks.LoadOrStore(key, &sync.Mutex{})
	mu := v.(*sync.Mutex)
	mu.Lock()
	return mu.Unlock
}

// InstallOptions controls `app install`.
type InstallOptions struct {
	Yes       bool
	DryRun    bool
	Force     bool
	NoInstall bool
	NoModel   bool
	Bundles   []string
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
	// PrepareOnly downloads/prepares the bundles without changing a running
	// app's state (the /prepare endpoint).
	PrepareOnly bool
}

// InstallResult describes what an install run did.
type InstallResult struct {
	State          AppState
	InstallRan     bool
	InstallSkipped bool
	AlreadyReady   bool
}

// installMu serializes installs in this process: preparing two applications at
// once would fight over disk.
var installMu sync.Mutex

// Install runs the flow from docs/plans/application_install_plan.md.
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
	unlock := lockApp(key)
	defer unlock()
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
	if found && (existing.State == StateReady || existing.State == StatePrepared) && !opts.Force {
		fmt.Fprintf(out, "\n%s %s is already installed (use --force to re-run).\n", key, m.Version)
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

	now := s.now().UTC().Format(time.RFC3339)
	if state.InstalledAt == "" {
		state.InstalledAt = now
	}
	state.UpdatedAt = now
	if opts.PrepareOnly && found {
		// Keep the live state/connection of an installed app while its bundles
		// are refreshed in the background.
		state.State = existing.State
		state.Connection = existing.Connection
	} else {
		state.State = StatePrepared
		// No model process exists; apps reach the gateway once activated.
		state.Connection = s.gatewayConnection(state.Models)
	}
	state.Error = ""
	s.save(&state)

	fmt.Fprintf(out, "\nInstalled %s %s (models prepared; not started)\n", key, m.Version)
	fmt.Fprintf(out, "Models:\n")
	for _, mdl := range state.Models {
		if mdl.Endpoint != "" {
			fmt.Fprintf(out, "  - %s  %s  (%s)\n", mdl.ID, mdl.Endpoint, mdl.Ref)
		} else {
			fmt.Fprintf(out, "  - %s  (%s) prepared\n", mdl.ID, mdl.Ref)
		}
	}
	if state.Connection.BaseURL != "" {
		fmt.Fprintf(out, "Connection: %s (api_key=%s)\n", state.Connection.BaseURL, state.Connection.APIKey)
	}
	res.State = state
	return res, nil
}

// applySetupScripts runs setup scripts after activation. For the CLI,
// ConfirmSetup prompts for each manifest script; the daemon passes the
// already-confirmed keys. A failure is logged and stops the remaining scripts.
func (s *Service) applySetupScripts(ctx context.Context, key string, st *AppState, setup SetupOptions, m *Manifest) {
	// A restore (no explicit selection; the daemon has no terminal) replays the
	// pinned definitions from the last confirmed run. The scripts need the new
	// {base_url}/{model}/{api_key}, which only exist now that the models are
	// ready; no manifest fetch is needed, so a daemon restart works offline.
	if !setup.Provided && s.ConfirmSetup == nil && len(st.SetupPlan) > 0 {
		st.SetupError = ""
		if err := s.runSetupScripts(ctx, st.SetupPlan, st, st.SetupClientHome); err != nil {
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
		if err := s.runSetupScripts(ctx, selected, st, setup.ClientHome); err != nil {
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

// Status returns the stored state with interrupted transitions normalized.
//
// The recorded state is reconciled with reality: after a daemon restart (or a
// crash/manual kill) an app can be stored as ready while its model process is
// gone. Reporting it as ready would disable 启动 and advertise a dead endpoint,
// so a ready app with no healthy model becomes stopped, and a partially healthy
// app becomes failed.
func (s *Service) Status(_ context.Context, key string) (AppState, error) {
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
	// UI's actions disabled forever. Only an old one is reported as failed.
	if isTransitional(st.State) && s.transitionExpired(&st) {
		st.State = StateFailed
		if st.Error == "" {
			st.Error = "previous operation was interrupted"
		}
		changed = true
	}
	if conn := s.gatewayConnection(st.Models); !reflect.DeepEqual(conn, st.Connection) {
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
	unlock := lockApp(key)
	defer unlock()
	st, ok, err := s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	ctx = WithOwner(ctx, key)
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

func (s *Service) gatewayBaseURL() string {
	if v := strings.TrimSpace(s.GatewayBaseURL); v != "" {
		v = strings.TrimRight(v, "/")
		if strings.HasSuffix(v, "/v1") {
			return v
		}
		return v + "/v1"
	}
	return "http://127.0.0.1:8790/v1"
}

// gatewayConnection describes how an app reaches the flashserver gateway.
func (s *Service) gatewayConnection(models []ModelState) Connection {
	conn := Connection{BaseURL: s.gatewayBaseURL(), APIKey: "local"}
	for _, m := range models {
		conn.Models = append(conn.Models, m.ID)
		conn.ModelRefs = append(conn.ModelRefs, m.Ref)
	}
	return conn
}

// Activate marks an installed app ready and runs its confirmed setup scripts.
// It never starts a model process: inference is served by the gateway.
func (s *Service) Activate(ctx context.Context, key string) (AppState, error) {
	return s.ActivateWithSetup(ctx, key, SetupOptions{})
}

// ActivateWithSetup is Activate with an explicit setup-script selection.
func (s *Service) ActivateWithSetup(ctx context.Context, key string, setup SetupOptions) (AppState, error) {
	unlock := lockApp(key)
	defer unlock()
	var st AppState
	var ok bool
	var err error
	capture := s.beginCapture()
	defer func() {
		s.endCapture(capture)
		if ok {
			st.LastLog = tailLog(capture.buf.String(), 100)
			s.save(&st)
		}
	}()
	st, ok, err = s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	ctx = WithOwner(ctx, key)
	st.State = StateReady
	st.Error = ""
	st.SetupError = ""
	st.Connection = s.gatewayConnection(st.Models)
	st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
	s.save(&st)
	m, _ := s.manifestFor(ctx, key)
	s.applySetupScripts(ctx, key, &st, setup, m)
	st.LastLog = tailLog(capture.buf.String(), 100)
	s.save(&st)
	return st, nil
}

// Deactivate marks an app stopped. Models belong to the gateway, so no process
// is stopped here.
func (s *Service) Deactivate(ctx context.Context, key string) (AppState, error) {
	unlock := lockApp(key)
	defer unlock()
	st, ok, err := s.Registry.Get(key)
	if err != nil {
		return AppState{}, err
	}
	if !ok {
		return AppState{}, fmt.Errorf("application %s is not installed", key)
	}
	st.State = StateStopped
	st.Error = ""
	st.SetupError = ""
	st.Connection = s.gatewayConnection(st.Models)
	st.UpdatedAt = s.now().UTC().Format(time.RFC3339)
	s.save(&st)
	return st, nil
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

// logCapture tees the operation output so it can be kept on the app state.
type logCapture struct {
	prev io.Writer
	buf  strings.Builder
}

func (c *logCapture) Write(p []byte) (int, error) {
	c.buf.Write(p)
	if c.prev != nil {
		_, _ = c.prev.Write(p)
	}
	return len(p), nil
}

func (s *Service) beginCapture() *logCapture {
	capture := &logCapture{prev: s.Out}
	s.Out = capture
	return capture
}

func (s *Service) endCapture(capture *logCapture) {
	s.Out = capture.prev
}

// tailLog keeps the last max lines (the state is persisted, so keep it small).
func tailLog(text string, max int) []string {
	text = strings.TrimRight(text, "\n")
	if strings.TrimSpace(text) == "" {
		return nil
	}
	lines := strings.Split(text, "\n")
	if len(lines) > max {
		lines = lines[len(lines)-max:]
	}
	return lines
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
