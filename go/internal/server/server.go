// Package server implements the local flashserver HTTP daemon.
package server

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/version"
)

// Source supplies local cached state to the API.
type Source interface {
	Models(context.Context) ([]host.Model, error)
	Storage(context.Context) ([]host.Area, error)
}

type defaultSource struct{}

func (defaultSource) Models(context.Context) ([]host.Model, error) { return host.ListModels() }
func (defaultSource) Storage(context.Context) ([]host.Area, error) { return host.Storage(), nil }

// Server is the local flashserver daemon. It schedules models; inference runs
// in separate `flashcli serve` processes.
type Server struct {
	Addr    string
	Token   string
	Source  Source
	Puller  Puller
	Jobs    *JobManager
	Manager *Manager
	GPU     func(context.Context) ([]gpu.Device, error)
	LogDir  string
	Started time.Time
}

// New creates a server with the default local configuration.
func New(addr string) *Server {
	if addr == "" {
		addr = "127.0.0.1:8790"
	}
	gpuProbe := gpu.Probe
	return &Server{
		Addr:    addr,
		Source:  defaultSource{},
		Puller:  hostPuller{},
		Jobs:    NewJobManager(),
		Manager: NewManagerWithOptions(FlashcliLauncher{}, ManagerOptions{GPU: gpuProbe}),
		GPU:     gpuProbe,
		Started: time.Now(),
	}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("GET /v1/system", s.system)
	mux.HandleFunc("GET /v1/logs", s.logs)
	mux.HandleFunc("GET /v1/version", s.version)
	mux.HandleFunc("GET /v1/models", s.models)
	mux.HandleFunc("GET /v1/models/loaded", s.loadedModels)
	mux.HandleFunc("GET /v1/storage", s.storage)
	mux.HandleFunc("GET /v1/resources", s.resources)
	mux.HandleFunc("GET /v1/gpu", s.gpuStatus)
	mux.HandleFunc("POST /v1/pull", s.pull)
	mux.HandleFunc("GET /v1/jobs/{id}", s.job)
	mux.HandleFunc("GET /v1/jobs/{id}/events", s.jobEvents)
	mux.HandleFunc("POST /v1/models/load", s.loadModel)
	mux.HandleFunc("POST /v1/models/unload", s.unloadModel)
	mux.HandleFunc("POST /v1/ui/chat", s.uiChat)
	mux.HandleFunc("GET /", s.ui)
	return s.authorize(mux)
}

func (s *Server) authorize(next http.Handler) http.Handler {
	if s.Token == "" {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" || r.URL.Path == "/" || strings.HasPrefix(r.URL.Path, "/ui/") {
			next.ServeHTTP(w, r)
			return
		}
		token := r.Header.Get("Authorization")
		if token == "Bearer "+s.Token || r.Header.Get("X-Flashcli-Token") == s.Token {
			next.ServeHTTP(w, r)
			return
		}
		writeJSON(w, http.StatusUnauthorized, map[string]any{"error": "unauthorized"})
	})
}

func (s *Server) Run(ctx context.Context) error {
	// Go treats the IPv4 wildcard 0.0.0.0 as a wildcard and may bind a
	// dual-stack socket. Windows' WSL localhost relay then exposes only ::1,
	// so explicit 127.0.0.1 clients fail. Pin the socket family to the
	// configured wildcard.
	network := "tcp"
	if host, _, err := net.SplitHostPort(s.Addr); err == nil {
		switch host {
		case "0.0.0.0":
			network = "tcp4"
		case "::", "[::]":
			network = "tcp6"
		}
	}
	ln, err := net.Listen(network, s.Addr)
	if err != nil {
		return err
	}
	srv := &http.Server{
		Handler:           s.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdownCtx)
		if s.Manager != nil {
			s.Manager.Close(shutdownCtx)
		}
	}()
	log.Printf("flashserver %s listening on http://%s", version.Version, ln.Addr())
	err = srv.Serve(ln)
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "version": version.Version})
}

func (s *Server) version(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"version": version.Version})
}

func (s *Server) models(w http.ResponseWriter, r *http.Request) {
	models, err := s.Source.Models(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"models": models, "loaded": s.loaded()})
}

func (s *Server) loadedModels(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"models": s.loaded()})
}

func (s *Server) loaded() []InstanceInfo {
	if s.Manager == nil {
		return []InstanceInfo{}
	}
	return s.Manager.List()
}

func (s *Server) resources(w http.ResponseWriter, r *http.Request) {
	out := map[string]any{"gpu": []any{}, "loaded": s.loaded()}
	if s.Manager != nil {
		loadedCount, maxLoaded := s.Manager.Slots()
		out["loaded_count"] = loadedCount
		out["max_loaded"] = maxLoaded
	}
	if s.GPU != nil {
		devices, err := s.GPU(r.Context())
		if err != nil {
			out["gpu_error"] = err.Error()
		} else {
			out["gpu"] = devices
		}
	}
	writeJSON(w, http.StatusOK, out)
}

func (s *Server) gpuStatus(w http.ResponseWriter, r *http.Request) {
	if s.GPU == nil {
		writeJSON(w, http.StatusOK, map[string]any{"devices": []any{}})
		return
	}
	devices, err := s.GPU(r.Context())
	if err != nil {
		writeError(w, http.StatusServiceUnavailable, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"devices": devices})
}

func (s *Server) storage(w http.ResponseWriter, r *http.Request) {
	areas, err := s.Source.Storage(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"areas": areas})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, err error) {
	writeJSON(w, status, map[string]any{"error": err.Error()})
}
