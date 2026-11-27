package apps

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// SetupOptions selects the setup scripts the user confirmed for this run.
// An empty Scripts list means "run none"; confirmation is per execution.
type SetupOptions struct {
	Scripts    []string
	ClientHome string
	// Provided distinguishes an explicit selection (possibly empty) from a
	// restore/no-selection call, which replays the saved selection.
	Provided bool
}

// runSetupScripts executes the selected setup script definitions in order. A
// failed script stops the remaining scripts and is returned as err.
func (s *Service) runSetupScripts(ctx context.Context, scripts []SetupScript, st *AppState, clientHome string) error {
	for _, script := range scripts {
		fmt.Fprintf(s.out(), "setup %s: %s\n", script.Key, script.URL)
		if err := s.runSetupScript(ctx, script, st.Connection, clientHome); err != nil {
			fmt.Fprintf(s.out(), "setup %s failed: %v\n", script.Key, err)
			return err
		}
		fmt.Fprintf(s.out(), "setup %s: done\n", script.Key)
	}
	return nil
}

func (s *Service) runSetupScript(ctx context.Context, script SetupScript, conn Connection, clientHome string) error {
	if !strings.EqualFold(strings.TrimSpace(script.Kind), "python") {
		return fmt.Errorf("unsupported setup kind %q", script.Kind)
	}
	if strings.TrimSpace(conn.BaseURL) == "" || len(conn.Models) == 0 {
		return fmt.Errorf("application is not running (no connection)")
	}
	blob, cached, err := s.setupScriptBytes(ctx, script)
	if err != nil {
		return err
	}
	if cached {
		fmt.Fprintf(s.out(), "setup %s: using verified cached script\n", script.Key)
	}
	args, err := setupArgs(script.Args, conn)
	if err != nil {
		return err
	}
	python, err := setupPython()
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp("", "flashcli-setup-*.py")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	if _, err := tmp.Write(blob); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	_ = os.Chmod(name, 0o700)

	cmd := exec.CommandContext(ctx, python, append([]string{name}, args...)...)
	cmd.Stdout = s.out()
	cmd.Stderr = s.out()
	cmd.Env = setupEnv(clientHome)
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("script failed: %w", err)
	}
	return nil
}

// setupScriptBytes returns a verified script body. The content-addressed cache
// (by manifest sha256) lets a restore replay without the network and avoids
// executing a transiently different CDN response.
func (s *Service) setupScriptBytes(ctx context.Context, script SetupScript) ([]byte, bool, error) {
	want := strings.ToLower(strings.TrimSpace(script.SHA256))
	path := ""
	if want != "" && s.Home != "" {
		path = filepath.Join(s.Home, "setup-cache", want+".py")
		if blob, err := os.ReadFile(path); err == nil {
			if setupHash(blob) == want {
				return blob, true, nil
			}
			// A corrupted cache must not hide a real failure.
			_ = os.Remove(path)
		}
	}
	blob, err := downloadSetupScript(ctx, script.URL)
	if err != nil {
		return nil, false, err
	}
	actual := setupHash(blob)
	if !strings.EqualFold(actual, want) {
		// CDN edges can briefly serve a stale/partial variant; retry once
		// before failing the integrity check.
		time.Sleep(300 * time.Millisecond)
		if retried, retryErr := downloadSetupScript(ctx, script.URL); retryErr == nil {
			blob = retried
			actual = setupHash(blob)
		}
	}
	if !strings.EqualFold(actual, want) {
		return nil, false, fmt.Errorf(
			"sha256 mismatch: manifest=%s actual=%s size=%d",
			strings.TrimSpace(script.SHA256), actual, len(blob),
		)
	}
	if path != "" {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err == nil {
			tmp := path + ".tmp"
			if err := os.WriteFile(tmp, blob, 0o600); err == nil {
				_ = os.Rename(tmp, path)
			} else {
				_ = os.Remove(tmp)
			}
		}
	}
	return blob, false, nil
}

func setupHash(blob []byte) string {
	sum := sha256.Sum256(blob)
	return hex.EncodeToString(sum[:])
}

func downloadSetupScript(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("download setup script: HTTP %d", resp.StatusCode)
	}
	blob, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, err
	}
	if len(blob) == 0 {
		return nil, fmt.Errorf("setup script is empty")
	}
	return blob, nil
}

// setupArgs renders the explicit argv template. Each entry is substituted and
// split into argv tokens (v1 values must not contain spaces).
func setupArgs(template []string, conn Connection) ([]string, error) {
	model := ""
	// Setup scripts must configure the app with the gateway's full bundle ref.
	// Connection.Models is the short display id; ModelRefs is authoritative.
	if len(conn.ModelRefs) > 0 {
		model = conn.ModelRefs[0]
	} else if len(conn.Models) > 0 {
		model = conn.Models[0]
	}
	apiKey := conn.APIKey
	if apiKey == "" {
		apiKey = "local"
	}
	replacer := strings.NewReplacer(
		"{base_url}", conn.BaseURL,
		"{model}", model,
		"{api_key}", apiKey,
	)
	var out []string
	for _, tpl := range template {
		fields := strings.Fields(replacer.Replace(tpl))
		if len(fields) == 0 {
			return nil, fmt.Errorf("setup arg %q is empty", tpl)
		}
		out = append(out, fields...)
	}
	return out, nil
}

func setupPython() (string, error) {
	if explicit := strings.TrimSpace(os.Getenv("FLASHCLI_SETUP_PYTHON")); explicit != "" {
		return explicit, nil
	}
	for _, name := range []string{"python3", "python"} {
		if path, err := exec.LookPath(name); err == nil {
			return path, nil
		}
	}
	return "", fmt.Errorf("no python interpreter found (set FLASHCLI_SETUP_PYTHON)")
}

// setupEnv maps the client OS home into the daemon's filesystem so a client-side
// script writes the application's real config (Windows path -> /mnt/<drive>/...).
func setupEnv(clientHome string) []string {
	home := strings.TrimSpace(clientHome)
	if home == "" {
		return os.Environ()
	}
	if runtime.GOOS != "windows" && len(home) >= 2 && home[1] == ':' {
		drive := strings.ToLower(home[:1])
		rest := strings.ReplaceAll(home[2:], `\`, "/")
		home = "/mnt/" + drive + rest
	}
	// Replace any existing HOME/USERPROFILE: duplicate entries in the child
	// environment are ambiguous and the script must see the client home.
	env := make([]string, 0, len(os.Environ())+2)
	for _, item := range os.Environ() {
		if strings.HasPrefix(item, "HOME=") || strings.HasPrefix(item, "USERPROFILE=") {
			continue
		}
		env = append(env, item)
	}
	env = append(env, "HOME="+home)
	if strings.Contains(clientHome, `\`) {
		env = append(env, "USERPROFILE="+clientHome)
	}
	return env
}
