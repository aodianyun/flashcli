// Package mirror ports flashcli_bundle.runtime.mirror: China-friendly endpoints
// for pip / PyTorch / Hugging Face, persisted in ~/.flashcli/mirror.env.
package mirror

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

const (
	// EnvFile is the persisted mirror config under FLASHCLI_HOME.
	EnvFile = "mirror.env"

	DefaultPipIndexURL    = "https://pypi.tuna.tsinghua.edu.cn/simple/"
	DefaultPipTrustedHost = "pypi.tuna.tsinghua.edu.cn"
	DefaultHFEndpoint     = "https://hf-mirror.com"
	// SJTU exposes a PEP 503 index (project pages like /cu128/torch/), so it can
	// be used as pip --index-url. Aliyun's pytorch-wheels is a flat file listing
	// (404 on /cu128/torch/) and does NOT work as an index.
	TorchIndexBase        = "https://mirror.sjtu.edu.cn/pytorch-wheels"
	OfficialTorchBase     = "https://download.pytorch.org/whl"
	DefaultGitProxyPrefix = "https://gh-proxy.com/"
)

var applied bool

func truthy(s string) bool {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

func envPath() string { return filepath.Join(paths.Home(), EnvFile) }

// Enabled mirrors mirror_enabled(): FLASHCLI_NO_MIRROR wins; else
// FLASHCLI_USE_MIRROR; else the presence of ~/.flashcli/mirror.env.
func Enabled() bool {
	if truthy(os.Getenv("FLASHCLI_NO_MIRROR")) {
		return false
	}
	if truthy(os.Getenv("FLASHCLI_USE_MIRROR")) {
		return true
	}
	_, err := os.Stat(envPath())
	return err == nil
}

// Apply is idempotent: load ~/.flashcli/mirror.env (setdefault per key), then
// apply default mirror endpoints when enabled.
func Apply() {
	if applied {
		return
	}
	applied = true
	if truthy(os.Getenv("FLASHCLI_NO_MIRROR")) {
		return
	}
	loadFile()
	if Enabled() {
		setDefault("PIP_INDEX_URL", DefaultPipIndexURL)
		setDefault("PIP_TRUSTED_HOST", DefaultPipTrustedHost)
		setDefault("HF_ENDPOINT", DefaultHFEndpoint)
		setDefault("FLASHCLI_PREFER_HF_MIRROR", "1")
		if !gitProxyDisabled() {
			setDefault("FLASHCLI_GIT_PROXY", DefaultGitProxyPrefix)
		}
	}
}

func loadFile() {
	blob, err := os.ReadFile(envPath())
	if err != nil {
		return
	}
	for _, line := range strings.Split(string(blob), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		eq := strings.IndexByte(line, '=')
		if eq < 0 {
			continue
		}
		key := strings.TrimSpace(line[:eq])
		val := strings.Trim(strings.TrimSpace(line[eq+1:]), `"'`)
		if key != "" && val != "" {
			setDefault(key, val)
		}
	}
}

func setDefault(key, val string) {
	if _, ok := os.LookupEnv(key); !ok {
		_ = os.Setenv(key, val)
	}
}

func gitProxyDisabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("FLASHCLI_GIT_PROXY"))) {
	case "0", "false", "no", "off":
		return true
	}
	return false
}

// PipExtraArgs returns extra `pip install` flags for the PyPI mirror.
func PipExtraArgs() []string {
	Apply()
	out := []string{}
	if url := strings.TrimSpace(os.Getenv("PIP_INDEX_URL")); url != "" {
		out = append(out, "--index-url", url)
		if host := strings.TrimSpace(os.Getenv("PIP_TRUSTED_HOST")); host != "" {
			out = append(out, "--trusted-host", host)
		}
	}
	return out
}

// TorchIndexURL resolves the PyTorch wheel index (Aliyun mirror when enabled).
func TorchIndexURL(index string) string {
	Apply()
	name := index
	if !strings.HasPrefix(name, "cu") {
		name = "cu" + name
	}
	if Enabled() {
		return TorchIndexBase + "/" + name + "/"
	}
	return OfficialTorchBase + "/" + name
}

// StatusLines mirrors mirror_status_lines() for doctor output.
func StatusLines() []string {
	Apply()
	if !Enabled() {
		return []string{"[i] Mirror: off (set FLASHCLI_USE_MIRROR=1 or re-run install.sh --mirror)"}
	}
	lines := []string{
		"[ok] Mirror: on",
		"     PIP_INDEX_URL=" + envOr("PIP_INDEX_URL", DefaultPipIndexURL),
		"     HF_ENDPOINT=" + envOr("HF_ENDPOINT", DefaultHFEndpoint),
	}
	if p := strings.TrimSpace(os.Getenv("FLASHCLI_GIT_PROXY")); p != "" && !gitProxyDisabled() {
		lines = append(lines, "     FLASHCLI_GIT_PROXY="+p)
	}
	if _, err := os.Stat(envPath()); err == nil {
		lines = append(lines, "     config: "+envPath())
	}
	return lines
}

func envOr(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}
