package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/aodianyun/flashcli/go/internal/host"
)

const (
	smokeRunTimeout     = 300 * time.Second
	smokeRequestTimeout = 120 * time.Second
	smokeLogLimit       = 128 << 10
)

type smokeRequest struct {
	Ref string `json:"ref"`
}

type smokeResult struct {
	Ref        string `json:"ref"`
	Kind       string `json:"kind"`
	OK         bool   `json:"ok"`
	DurationMS int64  `json:"duration_ms"`
	Status     int    `json:"status,omitempty"`
	Endpoint   string `json:"endpoint,omitempty"`
	Log        string `json:"log"`
	LogPath    string `json:"log_path,omitempty"`
}

// smokeModel runs a real smoke test for a cached model: `flashcli run <ref>`
// for run-only bundles, or one OpenAI-compatible chat request for a started
// serve model. The full output is appended to a log file and returned.
func (s *Server) smokeModel(w http.ResponseWriter, r *http.Request) {
	var req smokeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || strings.TrimSpace(req.Ref) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	refStr := strings.TrimSpace(req.Ref)
	models, err := host.ListModels()
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	var model *host.Model
	for i := range models {
		if models[i].Ref == refStr || models[i].CacheKey == refStr {
			model = &models[i]
			break
		}
	}
	if model == nil {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "model is not cached"})
		return
	}
	if !model.BundleCached || !model.WeightsCached {
		writeJSON(w, http.StatusConflict, map[string]any{"error": "model is not ready; load it first"})
		return
	}

	logPath := s.smokeLogPath(refStr)
	if model.Serve {
		if s.Manager == nil {
			writeError(w, http.StatusNotImplemented, fmt.Errorf("model manager is not configured"))
			return
		}
		endpoint, ok := s.Manager.Endpoint(refStr)
		if !ok {
			writeJSON(w, http.StatusConflict, map[string]any{"error": "model is not started; start it first"})
			return
		}
		result := s.smokeServeRequest(r.Context(), refStr, endpoint, logPath)
		writeJSON(w, http.StatusOK, result)
		return
	}
	result := s.smokeRun(r.Context(), refStr, logPath)
	writeJSON(w, http.StatusOK, result)
}

func (s *Server) smokeLogPath(refStr string) string {
	dir := strings.TrimSpace(s.LogDir)
	if dir == "" {
		dir = filepath.Join(os.TempDir(), "flashserver-smoke")
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return ""
	}
	name := strings.NewReplacer("/", "_", "\\", "_", ":", "_").Replace(refStr) + ".smoke.log"
	return filepath.Join(dir, name)
}

func (s *Server) smokeRun(ctx context.Context, refStr, logPath string) smokeResult {
	start := time.Now()
	result := smokeResult{Ref: refStr, Kind: "run", LogPath: logPath}
	bin, err := resolveFlashcliBin(s.FlashcliBin)
	if err != nil {
		result.Log = err.Error()
		result.DurationMS = time.Since(start).Milliseconds()
		return result
	}
	runCtx, cancel := context.WithTimeout(ctx, smokeRunTimeout)
	defer cancel()
	cmd := exec.CommandContext(runCtx, bin, "run", refStr)
	cmd.Env = os.Environ()
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	err = cmd.Run()
	result.DurationMS = time.Since(start).Milliseconds()
	result.OK = err == nil
	result.Log = appendSmokeLog(logPath, fmt.Sprintf(
		"=== run smoke %s ===\n$ %s run %s\n%s\nexit=%v duration=%dms\n",
		time.Now().Format(time.RFC3339), bin, refStr, out.String(), err, result.DurationMS))
	return result
}

func (s *Server) smokeServeRequest(ctx context.Context, refStr, endpoint, logPath string) smokeResult {
	start := time.Now()
	result := smokeResult{Ref: refStr, Kind: "serve", Endpoint: endpoint, LogPath: logPath}
	ctx, cancel := context.WithTimeout(ctx, smokeRequestTimeout)
	defer cancel()
	client := &http.Client{Timeout: smokeRequestTimeout}
	modelName := serveModelName(ctx, client, endpoint, refStr)
	body, _ := json.Marshal(map[string]any{
		"model":      modelName,
		"messages":   []map[string]string{{"role": "user", "content": "ping"}},
		"max_tokens": 32,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		strings.TrimRight(endpoint, "/")+"/v1/chat/completions", bytes.NewReader(body))
	if err != nil {
		result.Log = err.Error()
		result.DurationMS = time.Since(start).Milliseconds()
		return result
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	result.DurationMS = time.Since(start).Milliseconds()
	if err != nil {
		result.Log = appendSmokeLog(logPath, fmt.Sprintf(
			"=== serve smoke %s ===\nendpoint=%s model=%s request=%s\nerror=%v duration=%dms\n",
			time.Now().Format(time.RFC3339), endpoint, modelName, body, err, result.DurationMS))
		return result
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, smokeLogLimit))
	result.Status = resp.StatusCode
	result.OK = resp.StatusCode >= 200 && resp.StatusCode < 300
	result.Log = appendSmokeLog(logPath, fmt.Sprintf(
		"=== serve smoke %s ===\nendpoint=%s model=%s request=%s\nstatus=%d duration=%dms\nresponse=%s\n",
		time.Now().Format(time.RFC3339), endpoint, modelName, body, resp.StatusCode, result.DurationMS, data))
	return result
}

func serveModelName(ctx context.Context, client *http.Client, endpoint, refStr string) string {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(endpoint, "/")+"/v1/models", nil)
	if err == nil {
		if resp, err := client.Do(req); err == nil {
			defer resp.Body.Close()
			var payload struct {
				Data []struct {
					ID string `json:"id"`
				} `json:"data"`
			}
			if json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&payload) == nil && len(payload.Data) > 0 {
				if id := strings.TrimSpace(payload.Data[0].ID); id != "" {
					return id
				}
			}
		}
	}
	name := refStr
	if i := strings.LastIndex(name, ":"); i > 0 {
		name = name[:i]
	}
	if i := strings.LastIndex(name, "/"); i >= 0 {
		name = name[i+1:]
	}
	return name
}

func appendSmokeLog(path, entry string) string {
	if path != "" {
		if f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
			_, _ = io.WriteString(f, entry)
			_ = f.Close()
		}
	}
	if len(entry) > smokeLogLimit {
		entry = entry[len(entry)-smokeLogLimit:]
	}
	return entry
}
