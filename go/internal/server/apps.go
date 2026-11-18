package server

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/apps"
	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/paths"
)

// appService returns the shared application service (tests may override it).
// It installs a Manager-backed launcher so app models share the daemon's
// slot/VRAM admission with the 模型 page.
func (s *Server) appService() *apps.Service {
	if s.AppService != nil {
		return s.AppService()
	}
	svc := apps.New(paths.Home())
	if s.LogDir != "" {
		svc.LogDir = s.LogDir
	}
	if s.Manager != nil {
		svc.Launcher = managerLauncher{
			manager: s.Manager,
			Log: func(line string) {
				if svc.Out != nil {
					fmt.Fprintln(svc.Out, line)
				}
			},
		}
		// App models the model page loaded are not in this service's process
		// map; release them through the Manager (keeping models another app
		// still owns resident).
		svc.Stopper = func(ctx context.Context, refStr string) (bool, error) {
			return s.Manager.ReleaseFor(ctx, refStr, apps.OwnerFrom(ctx))
		}
		svc.Claim = func(ctx context.Context, refStr string) error {
			s.Manager.Claim(refStr, apps.OwnerFrom(ctx))
			return nil
		}
	}
	return svc
}

// appList serves GET /v1/apps: FlashHub applications with local state overlay.
func (s *Server) appList(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	list, total, err := flashhub.NewClient().ListApps(r.Context(), q.Get("search"), q.Get("domain"), atoiDefault(q.Get("page"), 1), atoiDefault(q.Get("page_size"), 20))
	if err != nil {
		writeError(w, http.StatusBadGateway, err)
		return
	}
	svc := s.appService()
	installed, _ := svc.Registry.Load()
	type item struct {
		flashhub.AppSummary
		Installed bool   `json:"installed"`
		State     string `json:"state,omitempty"`
	}
	out := make([]item, 0, len(list))
	for _, a := range list {
		it := item{AppSummary: a}
		key := flashhub.AppRef{Org: a.Organization.Name, Name: a.Name, Version: a.Version}.String()
		if st, ok := installed[key]; ok {
			it.Installed = true
			it.State = st.State
		}
		out = append(out, it)
	}
	writeJSON(w, http.StatusOK, map[string]any{"apps": out, "total": total})
}

// appManifest serves GET /v1/apps/{org}/{name}: manifest plus local state.
func (s *Server) appManifest(w http.ResponseWriter, r *http.Request) {
	ref := flashhub.AppRef{Org: r.PathValue("org"), Name: r.PathValue("name"), Version: r.URL.Query().Get("version")}
	blob, err := flashhub.NewClient().FetchAppManifest(r.Context(), ref)
	if err != nil {
		writeError(w, http.StatusBadGateway, err)
		return
	}
	var manifest map[string]any
	_ = json.Unmarshal(blob, &manifest)
	resp := map[string]any{"manifest": manifest, "org": ref.Org, "name": ref.Name, "version": ref.Version}
	svc := s.appService()
	if key, err := svc.ResolveKey(ref); err == nil {
		if st, ok, _ := svc.Registry.Get(key); ok {
			resp["local"] = st
		}
	}
	writeJSON(w, http.StatusOK, resp)
}

// appPrepare serves POST /v1/apps/{org}/{name}/prepare as an async job
// (pulls every default bundle; never runs install scripts).
func (s *Server) appPrepare(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Version string   `json:"version"`
		Bundles []string `json:"bundles"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	ref := flashhub.AppRef{Org: r.PathValue("org"), Name: r.PathValue("name"), Version: body.Version}
	if ref.Org == "" || ref.Name == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "org and name are required"})
		return
	}
	job := s.Jobs.Start(context.Background(), "app-prepare", ref.String(), func(ctx context.Context, emit func(string, string)) error {
		svc := s.appService()
		svc.Out = emitWriter{emit: emit}
		_, err := svc.Install(ctx, ref.String(), apps.InstallOptions{
			NoInstall: true,
			NoStart:   true,
			Force:     true,
			Bundles:   body.Bundles,
		})
		return err
	})
	writeJSON(w, http.StatusAccepted, map[string]any{"job_id": job.ID, "state": job.State})
}

// appInstall serves POST /v1/apps/{org}/{name}/install as an async job that
// runs the platform install command (when the caller allows it), prepares the
// default bundles, and starts the models.
//
// A daemon has no terminal, so it never guesses: `install_command` must be
// "run" (the user confirmed the command in the UI) or "skip" (install without
// the script). Missing/invalid values are rejected instead of silently running
// or skipping the script.
func (s *Server) appInstall(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Version        string   `json:"version"`
		Bundles        []string `json:"bundles"`
		InstallCommand string   `json:"install_command"`
		ClientOS       string   `json:"client_os"`
		ClientArch     string   `json:"client_arch"`
		Force          bool     `json:"force"`
		Start          *bool    `json:"start"`
		SetupScripts   []string `json:"setup_scripts"`
		ClientHome     string   `json:"client_home"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	ref := flashhub.AppRef{Org: r.PathValue("org"), Name: r.PathValue("name"), Version: body.Version}
	if ref.Org == "" || ref.Name == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "org and name are required"})
		return
	}
	var opts apps.InstallOptions
	switch strings.ToLower(strings.TrimSpace(body.InstallCommand)) {
	case "run":
		opts.Yes = true
	case "skip":
		opts.Confirm = func(string) bool { return false }
	case "client":
		opts.ScriptHandled = true
	default:
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error": `install_command is required: "run" executes the command on the daemon host, "skip" does not run it, "client" means the caller already ran it on its own platform`,
		})
		return
	}
	opts.OS = strings.TrimSpace(body.ClientOS)
	opts.Arch = strings.TrimSpace(body.ClientArch)
	opts.Force = body.Force
	opts.NoStart = body.Start != nil && !*body.Start
	opts.Bundles = body.Bundles
	opts.SetupScripts = body.SetupScripts
	opts.ClientHome = strings.TrimSpace(body.ClientHome)

	job := s.Jobs.Start(context.Background(), "app-install", ref.String(), func(ctx context.Context, emit func(string, string)) error {
		svc := s.appService()
		svc.Out = emitWriter{emit: emit}
		_, err := svc.Install(ctx, ref.String(), opts)
		return err
	})
	writeJSON(w, http.StatusAccepted, map[string]any{"job_id": job.ID, "state": job.State})
}

// appStart serves POST /v1/apps/{org}/{name}/start.
func (s *Server) appStart(w http.ResponseWriter, r *http.Request) {
	s.appLifecycle(w, r, "start")
}

// appStop serves POST /v1/apps/{org}/{name}/stop.
func (s *Server) appStop(w http.ResponseWriter, r *http.Request) {
	s.appLifecycle(w, r, "stop")
}

// appLifecycle starts or stops an application. The default response is the
// resulting AppState; `?async=1` returns a job whose events carry the start or
// stop progress (a model can take a minute to load, and a silent spinner is
// indistinguishable from a hang).
func (s *Server) appLifecycle(w http.ResponseWriter, r *http.Request, action string) {
	svc := s.appService()
	key, err := s.resolveAppKey(r, svc)
	if err != nil {
		writeError(w, http.StatusNotFound, err)
		return
	}
	var body struct {
		SetupScripts []string `json:"setup_scripts"`
		ClientHome   string   `json:"client_home"`
	}
	if r.Body != nil {
		_ = json.NewDecoder(r.Body).Decode(&body)
	}
	setup := apps.SetupOptions{
		Scripts:    body.SetupScripts,
		ClientHome: strings.TrimSpace(body.ClientHome),
	}
	if r.URL.Query().Get("async") == "1" {
		job := s.Jobs.Start(context.Background(), "app-"+action, key, func(ctx context.Context, emit func(string, string)) error {
			svc := s.appService()
			svc.Out = emitWriter{emit: emit}
			return runAppLifecycle(ctx, svc, action, key, setup)
		})
		writeJSON(w, http.StatusAccepted, map[string]any{"job_id": job.ID, "state": job.State})
		return
	}
	st, err := runAppLifecycleState(r.Context(), svc, action, key, setup)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	writeJSON(w, http.StatusOK, st)
}

func runAppLifecycle(ctx context.Context, svc *apps.Service, action, key string, setup apps.SetupOptions) error {
	_, err := runAppLifecycleState(ctx, svc, action, key, setup)
	return err
}

func runAppLifecycleState(ctx context.Context, svc *apps.Service, action, key string, setup apps.SetupOptions) (apps.AppState, error) {
	if action == "stop" {
		return svc.Stop(ctx, key)
	}
	return svc.StartWithSetup(ctx, key, false, setup)
}

// appStatus serves GET /v1/apps/{org}/{name}/status.
func (s *Server) appStatus(w http.ResponseWriter, r *http.Request) {
	svc := s.appService()
	key, err := s.resolveAppKey(r, svc)
	if err != nil {
		writeError(w, http.StatusNotFound, err)
		return
	}
	st, err := svc.Status(r.Context(), key)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, st)
}

// appUninstall serves DELETE /v1/apps/{org}/{name}.
func (s *Server) appUninstall(w http.ResponseWriter, r *http.Request) {
	svc := s.appService()
	key, err := s.resolveAppKey(r, svc)
	if err != nil {
		writeError(w, http.StatusNotFound, err)
		return
	}
	purge := r.URL.Query().Get("purge_models") == "1"
	st, err := svc.Uninstall(r.Context(), key, purge)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"app": key, "state": "uninstalled", "models": len(st.Models)})
}

// appInstalled serves GET /v1/apps/installed.
func (s *Server) appInstalled(w http.ResponseWriter, r *http.Request) {
	installed, err := s.appService().Registry.Load()
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"apps": installed})
}

func (s *Server) resolveAppKey(r *http.Request, svc *apps.Service) (string, error) {
	ref := flashhub.AppRef{Org: r.PathValue("org"), Name: r.PathValue("name"), Version: r.URL.Query().Get("version")}
	return svc.ResolveKey(ref)
}

// emitWriter turns service output lines into job progress events.
type emitWriter struct {
	emit func(phase, message string)
}

func (w emitWriter) Write(p []byte) (int, error) {
	for _, line := range strings.Split(string(p), "\n") {
		if line = strings.TrimSpace(line); line != "" {
			w.emit("app", line)
		}
	}
	return len(p), nil
}

var _ io.Writer = emitWriter{}

func atoiDefault(s string, def int) int {
	var n int
	if _, err := fmt.Sscanf(strings.TrimSpace(s), "%d", &n); err != nil || n <= 0 {
		return def
	}
	return n
}
