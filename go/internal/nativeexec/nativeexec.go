// Package nativeexec runs a bundle's `native-exec` entry: a separate process
// spoken to over NDJSON stdio or HTTP. Mirrors docs/bundle_execution_abi.md
// section 6.
package nativeexec

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

// Spec is a resolved native-exec spec.
type Spec struct {
	Command         []string
	Cwd             string // "bundle" or absolute
	Transport       string // "stdio" or "http"
	ReadyTimeout    time.Duration
	ShutdownTimeout time.Duration
	Env             map[string]string
}

// SpecFromEntry parses entry.<cap>.native for kind == native-exec.
func SpecFromEntry(e *manifest.EntrySpec) (Spec, error) {
	raw := e.Native
	command := stringList(raw["command"])
	if len(command) == 0 {
		return Spec{}, errors.New("entry.native.command must be a non-empty array of strings")
	}
	cwd := strings.TrimSpace(stringValue(raw["cwd"]))
	if cwd == "" {
		cwd = "bundle"
	}
	transport := strings.ToLower(strings.TrimSpace(stringValue(raw["transport"])))
	if transport == "" {
		transport = "stdio"
	}
	if transport != "stdio" && transport != "http" {
		return Spec{}, fmt.Errorf("entry.native.transport must be 'stdio' or 'http', got %q", transport)
	}
	env := map[string]string{}
	for k, v := range mapValue(raw["env"]) {
		if s, ok := v.(string); ok {
			env[k] = s
		}
	}
	return Spec{
		Command:         command,
		Cwd:             cwd,
		Transport:       transport,
		ReadyTimeout:    secondsOr(raw["ready_timeout_sec"], 120),
		ShutdownTimeout: secondsOr(raw["shutdown_timeout_sec"], 10),
		Env:             env,
	}, nil
}

// Placeholders are substituted into command args and config.
type Placeholders struct {
	Checkpoint string
	BundleRoot string
	ModelsDir  string
	Preset     string
	Variant    string
	RuntimeDir string
	Extra      map[string]string
	Options    map[string]string
}

// Resolve substitutes {checkpoint}, {bundle_root}, {models_dir}, {preset},
// {variant}, {runtime_dir}, {extra:<key>} and {option:<name>} in s.
func (p Placeholders) Resolve(s string) string {
	repl := map[string]string{
		"checkpoint":  p.Checkpoint,
		"bundle_root": p.BundleRoot,
		"models_dir":  p.ModelsDir,
		"preset":      p.Preset,
		"variant":     p.Variant,
		"runtime_dir": p.RuntimeDir,
	}
	for k, v := range repl {
		s = strings.ReplaceAll(s, "{"+k+"}", v)
	}
	for k, v := range p.Extra {
		s = strings.ReplaceAll(s, "{extra:"+k+"}", v)
	}
	for k, v := range p.Options {
		s = strings.ReplaceAll(s, "{option:"+k+"}", v)
	}
	return s
}

// ScriptEnv returns the shared script-mode env vars for a native start.
func (p Placeholders) ScriptEnv() []string {
	env := []string{
		"FLASHCLI_CHECKPOINT=" + p.Checkpoint,
		"FLASHCLI_BUNDLE_ROOT=" + p.BundleRoot,
		"FLASHCLI_PRESET=" + p.Preset,
	}
	if p.Variant != "" {
		env = append(env, "FLASHCLI_VARIANT="+p.Variant)
	}
	for key, path := range p.Extra {
		env = append(env, "FLASHCLI_EXTRA_WEIGHT_"+envKey(key)+"="+path)
	}
	return env
}

func envKey(key string) string {
	var b strings.Builder
	for _, r := range strings.ToUpper(key) {
		if (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' {
			b.WriteRune(r)
		} else {
			b.WriteByte('_')
		}
	}
	return b.String()
}

type request struct {
	V       int            `json:"v"`
	ID      int            `json:"id"`
	Op      string         `json:"op"`
	Payload map[string]any `json:"payload"`
}

type wireError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type response struct {
	V       int            `json:"v"`
	ID      int            `json:"id"`
	Op      string         `json:"op"`
	OK      *bool          `json:"ok"`
	Payload map[string]any `json:"payload"`
	Error   *wireError     `json:"error"`
}

// Process is a running native-exec backend.
type Process struct {
	cmd             *exec.Cmd
	stdin           io.WriteCloser
	lines           chan string
	transport       string
	endpoint        string
	shutdownTimeout time.Duration
	nextID          int
	client          *http.Client
	ready           map[string]any
}

// Ready returns the backend's readiness payload.
func (p *Process) Ready() map[string]any { return p.ready }

// Start spawns the backend and waits for its readiness message.
func Start(ctx context.Context, spec Spec, ph Placeholders, extraEnv []string) (*Process, error) {
	argv := make([]string, len(spec.Command))
	for i, a := range spec.Command {
		argv[i] = ph.Resolve(a)
	}

	cmd := exec.Command(argv[0], argv[1:]...)
	if spec.Cwd == "bundle" {
		cmd.Dir = ph.BundleRoot
	} else {
		cmd.Dir = spec.Cwd
	}
	env := append(os.Environ(), ph.ScriptEnv()...)
	for k, v := range spec.Env {
		env = append(env, k+"="+v)
	}
	cmd.Env = append(env, extraEnv...)

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		return nil, err
	}

	p := &Process{
		cmd:             cmd,
		stdin:           stdin,
		lines:           make(chan string, 16),
		transport:       spec.Transport,
		shutdownTimeout: spec.ShutdownTimeout,
		client:          &http.Client{},
	}
	go p.pump(stdout)

	ready, err := p.awaitReady(ctx, spec.ReadyTimeout)
	if err != nil {
		_ = p.cmd.Process.Kill()
		return nil, err
	}
	p.ready = ready
	if spec.Transport == "http" {
		p.endpoint = stringValue(ready["endpoint"])
		if p.endpoint == "" {
			_ = p.cmd.Process.Kill()
			return nil, errors.New("native-exec http backend ready message missing endpoint")
		}
	}
	return p, nil
}

func (p *Process) pump(stdout io.ReadCloser) {
	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 64*1024), 16*1024*1024)
	for scanner.Scan() {
		p.lines <- scanner.Text()
	}
	close(p.lines)
}

func (p *Process) awaitReady(ctx context.Context, timeout time.Duration) (map[string]any, error) {
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	for {
		select {
		case line, ok := <-p.lines:
			if !ok {
				return nil, errors.New("native-exec process exited before readiness")
			}
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var msg map[string]any
			if err := json.Unmarshal([]byte(line), &msg); err != nil {
				continue
			}
			if stringValue(msg["op"]) == "ready" {
				payload, _ := msg["payload"].(map[string]any)
				return payload, nil
			}
		case <-timer.C:
			return nil, fmt.Errorf("native-exec not ready within %s", timeout)
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
}

// Run sends one inference request and returns its payload.
func (p *Process) Run(ctx context.Context, payload map[string]any) (map[string]any, error) {
	if p.transport == "http" {
		return p.runHTTP(ctx, payload)
	}
	id := p.nextID
	p.nextID++
	req := request{V: 1, ID: id, Op: "run", Payload: payload}
	blob, _ := json.Marshal(req)
	if _, err := p.stdin.Write(append(blob, '\n')); err != nil {
		return nil, err
	}
	return p.readResponse(ctx, id)
}

func (p *Process) readResponse(ctx context.Context, id int) (map[string]any, error) {
	for {
		select {
		case line, ok := <-p.lines:
			if !ok {
				return nil, errors.New("native-exec process exited")
			}
			var resp response
			if err := json.Unmarshal([]byte(line), &resp); err != nil {
				continue
			}
			if resp.ID != id || resp.OK == nil {
				continue
			}
			if !*resp.OK {
				if resp.Error != nil {
					return nil, fmt.Errorf("native-exec error %d: %s", resp.Error.Code, resp.Error.Message)
				}
				return nil, errors.New("native-exec returned failure")
			}
			return resp.Payload, nil
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
}

func (p *Process) runHTTP(ctx context.Context, payload map[string]any) (map[string]any, error) {
	body, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(p.endpoint, "/")+"/run", strings.NewReader(string(body)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("native-exec http /run: HTTP %d", resp.StatusCode)
	}
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return out, nil
}

// Close shuts the backend down gracefully, then kills it if needed.
func (p *Process) Close(ctx context.Context) error {
	if p.transport == "http" {
		_ = p.cmd.Process.Signal(os.Interrupt)
	} else {
		id := p.nextID
		p.nextID++
		blob, _ := json.Marshal(request{V: 1, ID: id, Op: "shutdown", Payload: map[string]any{}})
		_, _ = p.stdin.Write(append(blob, '\n'))
	}
	_ = p.stdin.Close()

	done := make(chan error, 1)
	go func() { done <- p.cmd.Wait() }()
	select {
	case err := <-done:
		return err
	case <-time.After(p.shutdownTimeout):
		_ = p.cmd.Process.Kill()
		return <-done
	case <-ctx.Done():
		_ = p.cmd.Process.Kill()
		return <-done
	}
}

// --- small helpers ---------------------------------------------------------

func stringValue(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func stringList(v any) []string {
	list, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(list))
	for _, item := range list {
		if s, ok := item.(string); ok && s != "" {
			out = append(out, s)
		}
	}
	return out
}

func mapValue(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return nil
}

func secondsOr(v any, fallback int) time.Duration {
	switch n := v.(type) {
	case float64:
		return time.Duration(n) * time.Second
	case int:
		return time.Duration(n) * time.Second
	case string:
		if i, err := strconv.Atoi(strings.TrimSpace(n)); err == nil {
			return time.Duration(i) * time.Second
		}
	}
	return time.Duration(fallback) * time.Second
}
