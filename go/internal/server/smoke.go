package server

import (
	"bufio"
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
	"sync"
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

// smokeModel validates a cached model and starts an async smoke job. Job
// output is streamed over the existing WebSocket job channel and appended to
// <ref>.smoke.log.
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
	if s.Jobs == nil {
		writeError(w, http.StatusNotImplemented, fmt.Errorf("job manager is not configured"))
		return
	}

	kind := "run"
	endpoint := ""
	if model.Serve {
		if s.Manager == nil {
			writeError(w, http.StatusNotImplemented, fmt.Errorf("model manager is not configured"))
			return
		}
		endpoint, _ = s.Manager.Endpoint(refStr)
		if endpoint == "" {
			writeJSON(w, http.StatusConflict, map[string]any{"error": "model is not started; start it first"})
			return
		}
		kind = "serve"
	}

	logPath := s.smokeLogPath(refStr)
	job := s.Jobs.Start(context.Background(), "smoke", refStr, func(ctx context.Context, emit func(string, string)) error {
		emit("smoke", "日志文件: "+logPath)
		if kind == "serve" {
			return s.smokeServeRequest(ctx, refStr, endpoint, logPath, emit)
		}
		return s.smokeRun(ctx, refStr, logPath, emit)
	})
	writeJSON(w, http.StatusAccepted, map[string]any{
		"job_id":   job.ID,
		"state":    job.State,
		"kind":     kind,
		"ref":      refStr,
		"log_path": logPath,
	})
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

func (s *Server) smokeRun(ctx context.Context, refStr, logPath string, emit func(string, string)) error {
	bin, err := resolveFlashcliBin(s.FlashcliBin)
	if err != nil {
		appendSmokeLog(logPath, "启动失败: "+err.Error()+"\n")
		return err
	}
	runCtx, cancel := context.WithTimeout(ctx, smokeRunTimeout)
	defer cancel()
	appendSmokeLog(logPath, fmt.Sprintf("\n=== run smoke %s ===\n$ %s run %s\n", time.Now().Format(time.RFC3339), bin, refStr))
	var cmd *exec.Cmd
	if nice, err := exec.LookPath("nice"); err == nil {
		cmd = exec.CommandContext(runCtx, nice, "-n", "10", bin, "run", refStr)
	} else {
		cmd = exec.CommandContext(runCtx, bin, "run", refStr)
	}
	cmd.Env = os.Environ()
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	start := time.Now()
	if err := cmd.Start(); err != nil {
		appendSmokeLog(logPath, "启动失败: "+err.Error()+"\n")
		return err
	}
	var wg sync.WaitGroup
	read := func(r io.Reader) {
		defer wg.Done()
		scanner := bufio.NewScanner(r)
		scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
		for scanner.Scan() {
			line := strings.TrimRight(scanner.Text(), "\r")
			if line == "" {
				continue
			}
			appendSmokeLog(logPath, line+"\n")
			emit("smoke", line)
		}
	}
	wg.Add(2)
	go read(stdout)
	go read(stderr)
	err = cmd.Wait()
	wg.Wait()
	duration := time.Since(start).Milliseconds()
	appendSmokeLog(logPath, fmt.Sprintf("exit=%v duration=%dms\n", err, duration))
	emit("smoke", fmt.Sprintf("exit=%v duration=%dms", err, duration))
	return err
}

func (s *Server) smokeServeRequest(ctx context.Context, refStr, endpoint, logPath string, emit func(string, string)) error {
	ctx, cancel := context.WithTimeout(ctx, smokeRequestTimeout)
	defer cancel()
	client := &http.Client{Timeout: smokeRequestTimeout}
	modelName := serveModelName(ctx, client, endpoint, refStr)
	body, _ := json.Marshal(map[string]any{
		"model":      modelName,
		"messages":   []map[string]string{{"role": "user", "content": "ping"}},
		"max_tokens": 32,
	})
	start := time.Now()
	appendSmokeLog(logPath, fmt.Sprintf("\n=== serve smoke %s ===\nendpoint=%s model=%s request=%s\n",
		time.Now().Format(time.RFC3339), endpoint, modelName, body))
	emit("smoke", fmt.Sprintf("POST %s/v1/chat/completions model=%s", strings.TrimRight(endpoint, "/"), modelName))
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		strings.TrimRight(endpoint, "/")+"/v1/chat/completions", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	duration := time.Since(start).Milliseconds()
	if err != nil {
		appendSmokeLog(logPath, fmt.Sprintf("error=%v duration=%dms\n", err, duration))
		emit("smoke", fmt.Sprintf("error=%v duration=%dms", err, duration))
		return err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, smokeLogLimit))
	appendSmokeLog(logPath, fmt.Sprintf("status=%d duration=%dms\nresponse=%s\n", resp.StatusCode, duration, data))
	emit("smoke", fmt.Sprintf("status=%d duration=%dms", resp.StatusCode, duration))
	if len(data) > 0 {
		emit("smoke", "response="+string(data))
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("serve request returned HTTP %d", resp.StatusCode)
	}
	return nil
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

func appendSmokeLog(path, entry string) {
	if path != "" {
		if f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
			_, _ = io.WriteString(f, entry)
			_ = f.Close()
		}
	}
}
