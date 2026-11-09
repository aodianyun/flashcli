package server

import (
	"bytes"
	"embed"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/version"
)

//go:embed web/*
var webFS embed.FS

//go:embed openapi.yaml
var openapiDoc []byte

func (s *Server) openapi(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/yaml; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	_, _ = w.Write(openapiDoc)
}

func (s *Server) system(w http.ResponseWriter, r *http.Request) {
	out := map[string]any{
		"version":               version.Version,
		"protocol_version":      version.ProtocolVersion,
		"runtime_abi_version":   version.RuntimeABIVersion,
		"exec_protocol_version": version.ExecProtocolVersion,
		"os":                    runtime.GOOS,
		"arch":                  runtime.GOARCH,
		"started_at":            s.Started.UTC().Format(time.RFC3339),
		"uptime_seconds":        int64(time.Since(s.Started).Seconds()),
		"wsl":                   isWSL(),
		"auth":                  s.Token != "",
	}
	if host, err := os.Hostname(); err == nil {
		out["hostname"] = host
	}
	if blob, err := os.ReadFile("/proc/sys/kernel/osrelease"); err == nil {
		out["kernel"] = strings.TrimSpace(string(blob))
	}
	if s.GPU != nil {
		if devices, err := s.GPU(r.Context()); err == nil {
			out["gpu"] = devices
		} else {
			out["gpu_error"] = err.Error()
		}
	}
	if driver, err := gpu.DriverVersion(r.Context()); err == nil && driver != "" {
		out["driver_version"] = driver
	}
	if cuda, err := gpu.CUDAVersion(r.Context()); err == nil && cuda != "" {
		out["cuda_version"] = cuda
	}
	if info := preflight.DetectGPU(); info != nil {
		out["sm"] = info.SM
		out["cuda_tag"] = "cu" + info.CudaTag
		if info.TorchIndex != "" {
			out["torch_index"] = info.TorchIndex
		}
	}
	if s.Manager != nil {
		loaded, maxLoaded := s.Manager.Slots()
		out["loaded_count"] = loaded
		out["max_loaded"] = maxLoaded
	}
	writeJSON(w, http.StatusOK, out)
}

func isWSL() bool {
	if os.Getenv("WSL_DISTRO_NAME") != "" {
		return true
	}
	blob, err := os.ReadFile("/proc/version")
	return err == nil && strings.Contains(strings.ToLower(string(blob)), "microsoft")
}

func (s *Server) logs(w http.ResponseWriter, r *http.Request) {
	n := 200
	if raw := r.URL.Query().Get("lines"); raw != "" {
		if v, err := strconv.Atoi(raw); err == nil {
			n = v
		}
	}
	if n < 1 {
		n = 1
	}
	if n > 2000 {
		n = 2000
	}
	kind := r.URL.Query().Get("kind")
	switch kind {
	case "", "server":
		writeJSON(w, http.StatusOK, map[string]any{"kind": "server", "lines": serverLogLines(n)})
	case "model":
		refStr := strings.TrimSpace(r.URL.Query().Get("ref"))
		if refStr == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
			return
		}
		if s.LogDir == "" {
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "serve log directory is not configured"})
			return
		}
		path := filepath.Join(s.LogDir, serveLogName(refStr))
		lines, err := tailFile(path, n)
		if err != nil {
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "log not found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"kind": "model", "ref": refStr, "lines": lines})
	default:
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "kind must be server or model"})
	}
}

func serveLogName(refStr string) string {
	return strings.NewReplacer("/", "_", "\\", "_", ":", "_").Replace(refStr) + ".log"
}

func tailFile(path string, n int) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	const window = 256 * 1024
	off := info.Size() - window
	if off < 0 {
		off = 0
	}
	if _, err := f.Seek(off, io.SeekStart); err != nil {
		return nil, err
	}
	blob, err := io.ReadAll(f)
	if err != nil {
		return nil, err
	}
	all := strings.Split(strings.TrimRight(string(blob), "\n"), "\n")
	if off > 0 && len(all) > 0 {
		all = all[1:] // drop the partial first line
	}
	if n > len(all) {
		n = len(all)
	}
	return all[len(all)-n:], nil
}

// ui serves the embedded local console.
func (s *Server) ui(w http.ResponseWriter, r *http.Request) {
	switch {
	case r.URL.Path == "/" || r.URL.Path == "":
		blob, err := readWeb("index.html")
		if err != nil {
			http.NotFound(w, r)
			return
		}
		html := strings.ReplaceAll(string(blob), "__FLASHCLI_TOKEN__", s.Token)
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-cache")
		_, _ = w.Write([]byte(html))
	case strings.HasPrefix(r.URL.Path, "/ui/"):
		name := strings.TrimPrefix(r.URL.Path, "/ui/")
		if name == "" || strings.Contains(name, "..") {
			http.NotFound(w, r)
			return
		}
		blob, err := readWeb(name)
		if err != nil {
			http.NotFound(w, r)
			return
		}
		switch {
		case strings.HasSuffix(name, ".css"):
			w.Header().Set("Content-Type", "text/css; charset=utf-8")
		case strings.HasSuffix(name, ".js"):
			w.Header().Set("Content-Type", "application/javascript; charset=utf-8")
		case strings.HasSuffix(name, ".svg"):
			w.Header().Set("Content-Type", "image/svg+xml")
		default:
			w.Header().Set("Content-Type", "application/octet-stream")
		}
		w.Header().Set("Cache-Control", "no-cache")
		_, _ = w.Write(blob)
	default:
		http.NotFound(w, r)
	}
}

// readWeb serves UI assets from FLASHCLI_WEB_DIR when set (development /
// customization) and from the embedded copy otherwise.
func readWeb(name string) ([]byte, error) {
	if dir := strings.TrimSpace(os.Getenv("FLASHCLI_WEB_DIR")); dir != "" {
		if blob, err := os.ReadFile(filepath.Join(dir, name)); err == nil {
			return blob, nil
		}
	}
	return webFS.ReadFile("web/" + name)
}

// uiChat forwards one OpenAI chat request to a loaded model. It exists so the
// local console can talk to model endpoints without CORS; the public contract
// remains "load returns an endpoint".
func (s *Server) uiChat(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Ref  string          `json:"ref"`
		Body json.RawMessage `json:"body"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Ref == "" || len(req.Body) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref and body are required"})
		return
	}
	if s.Manager == nil {
		writeError(w, http.StatusNotImplemented, errors.New("model manager is not configured"))
		return
	}
	endpoint, ok := s.Manager.Endpoint(req.Ref)
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "model is not loaded"})
		return
	}
	up, err := http.NewRequestWithContext(r.Context(), http.MethodPost, endpoint+"/v1/chat/completions", bytes.NewReader(req.Body))
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	up.Header.Set("Content-Type", "application/json")
	if accept := r.Header.Get("Accept"); accept != "" {
		up.Header.Set("Accept", accept)
	}
	resp, err := http.DefaultClient.Do(up)
	if err != nil {
		writeError(w, http.StatusBadGateway, err)
		return
	}
	defer resp.Body.Close()
	if ct := resp.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
	}
	w.WriteHeader(resp.StatusCode)
	flusher, _ := w.(http.Flusher)
	buf := make([]byte, 32*1024)
	for {
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, err := w.Write(buf[:n]); err != nil {
				return
			}
			if flusher != nil {
				flusher.Flush()
			}
		}
		if readErr != nil {
			return
		}
	}
}
