// Package apps implements FlashHub application installs and lifecycle for both
// `flashcli app` (standalone) and flashserver (HTTP). One implementation, two
// frontends; the manifest is specified in docs/app_manifest_standard.md.
package apps

import (
	"encoding/json"
	"fmt"
	"runtime"
	"strings"
)

// Bundle is one model bundle referenced by an application.
type Bundle struct {
	Bundle  string `json:"bundle"`
	Default bool   `json:"default"`
	Serve   struct {
		Options map[string]any `json:"options"`
	} `json:"serve"`
}

// SetupScript is a client-side configuration script declared by an application.
// It is downloaded, verified against SHA256, and executed with an explicit argv
// template (placeholders {base_url}, {model}, {api_key}).
type SetupScript struct {
	Key    string   `json:"key"`
	Kind   string   `json:"kind"`
	URL    string   `json:"url"`
	SHA256 string   `json:"sha256"`
	Args   []string `json:"args"`
}

// Manifest is a FlashHub application manifest (app_format_version 1).
type Manifest struct {
	Format           string `json:"format"`
	AppFormatVersion int    `json:"app_format_version"`
	ProtocolVersion  int    `json:"protocol_version"`
	Name             string `json:"name"`
	Version          string `json:"version"`
	DisplayName      string `json:"display_name"`
	Supported        struct {
		OS   []string `json:"os"`
		Arch []string `json:"arch"`
	} `json:"supported"`
	Install struct {
		Commands map[string]string `json:"commands"`
	} `json:"install"`
	Model struct {
		Bundles []Bundle `json:"bundles"`
	} `json:"model"`
	Config []any `json:"config"`
	Setup  struct {
		Scripts []SetupScript `json:"scripts"`
	} `json:"setup"`
}

// Parse decodes and validates an application manifest.
func Parse(raw []byte) (*Manifest, error) {
	var m Manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, fmt.Errorf("application manifest is not JSON: %w", err)
	}
	if errs := Validate(&m); len(errs) > 0 {
		return nil, fmt.Errorf("invalid application manifest: %s", strings.Join(errs, "; "))
	}
	return &m, nil
}

// Validate reports schema errors for an application manifest.
func Validate(m *Manifest) []string {
	var errs []string
	if m.Format != "flashcli-application" {
		errs = append(errs, fmt.Sprintf("format must be %q, got %q", "flashcli-application", m.Format))
	}
	if m.AppFormatVersion != 1 {
		errs = append(errs, fmt.Sprintf("unsupported app_format_version %d (expected 1; upgrade flashcli)", m.AppFormatVersion))
	}
	if strings.TrimSpace(m.Name) == "" {
		errs = append(errs, "name is required")
	}
	if strings.TrimSpace(m.Version) == "" {
		errs = append(errs, "version is required")
	}
	if len(m.Supported.OS) == 0 || len(m.Supported.Arch) == 0 {
		errs = append(errs, "supported.os and supported.arch are required")
	}
	if len(m.Install.Commands) == 0 {
		errs = append(errs, "install.commands is required")
	}
	if len(m.Model.Bundles) == 0 {
		errs = append(errs, "model.bundles is required")
	}
	for i, b := range m.Model.Bundles {
		if strings.TrimSpace(b.Bundle) == "" {
			errs = append(errs, fmt.Sprintf("model.bundles[%d].bundle is required", i))
		}
	}
	seenScripts := map[string]bool{}
	for i, s := range m.Setup.Scripts {
		prefix := fmt.Sprintf("setup.scripts[%d]", i)
		key := strings.TrimSpace(s.Key)
		switch {
		case key == "":
			errs = append(errs, prefix+".key is required")
		case seenScripts[key]:
			errs = append(errs, fmt.Sprintf("%s.key %q is duplicated", prefix, key))
		default:
			seenScripts[key] = true
		}
		if !strings.EqualFold(strings.TrimSpace(s.Kind), "python") {
			errs = append(errs, prefix+`.kind must be "python"`)
		}
		if u := strings.TrimSpace(s.URL); !strings.HasPrefix(strings.ToLower(u), "https://") {
			errs = append(errs, prefix+".url must be an https:// URL")
		}
		if !isHex64(s.SHA256) {
			errs = append(errs, prefix+".sha256 must be 64 hex characters")
		}
		for j, arg := range s.Args {
			if strings.TrimSpace(arg) == "" {
				errs = append(errs, fmt.Sprintf("%s.args[%d] must not be empty", prefix, j))
				continue
			}
			if strings.ContainsAny(arg, "\x00\r\n") {
				errs = append(errs, fmt.Sprintf("%s.args[%d] must be a single line", prefix, j))
				continue
			}
			if msg := setupArgError(arg); msg != "" {
				errs = append(errs, fmt.Sprintf("%s.args[%d]: %s", prefix, j, msg))
			}
		}
	}
	return errs
}

func isHex64(s string) bool {
	s = strings.TrimSpace(s)
	if len(s) != 64 {
		return false
	}
	for _, c := range s {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')) {
			return false
		}
	}
	return true
}

// setupArgError validates the explicit argv template placeholders.
func setupArgError(arg string) string {
	for i := 0; i < len(arg); i++ {
		switch arg[i] {
		case '{':
			j := strings.IndexByte(arg[i+1:], '}')
			if j < 0 {
				return "unterminated placeholder"
			}
			switch name := arg[i+1 : i+1+j]; name {
			case "base_url", "model", "api_key":
			default:
				return fmt.Sprintf("unknown placeholder {%s}", name)
			}
			i += j + 1
		case '}':
			return "unexpected '}'"
		}
	}
	return ""
}

// Supported reports whether the manifest supports this OS/arch.
func Supported(m *Manifest, goos, goarch string) bool {
	return containsFold(m.Supported.OS, normalizeOS(goos)) &&
		containsFold(m.Supported.Arch, normalizeArch(goarch))
}

// PlatformCommand picks the install command for the host, preferring the
// "<os>/<arch>" entry over the plain "<os>" one.
func PlatformCommand(m *Manifest, goos, goarch string) (key, command string, ok bool) {
	osName, arch := normalizeOS(goos), normalizeArch(goarch)
	for _, candidate := range []string{osName + "/" + arch, osName} {
		for k, v := range m.Install.Commands {
			if strings.EqualFold(strings.TrimSpace(k), candidate) && strings.TrimSpace(v) != "" {
				return k, strings.TrimSpace(v), true
			}
		}
	}
	return "", "", false
}

// DefaultBundles returns the bundles to prepare: explicit overrides when given,
// otherwise every bundle marked default (falling back to the first one).
func DefaultBundles(m *Manifest, overrides []string) []string {
	if len(overrides) > 0 {
		out := make([]string, 0, len(overrides))
		for _, ref := range overrides {
			if ref = strings.TrimSpace(ref); ref != "" {
				out = append(out, ref)
			}
		}
		return out
	}
	var out []string
	for _, b := range m.Model.Bundles {
		if b.Default {
			out = append(out, b.Bundle)
		}
	}
	if len(out) == 0 && len(m.Model.Bundles) > 0 {
		out = append(out, m.Model.Bundles[0].Bundle)
	}
	return out
}

// IsURL reports whether an install command is a plain download URL rather than
// a shell command.
func IsURL(command string) bool {
	c := strings.TrimSpace(command)
	if strings.ContainsAny(c, " \t|&;<>$`") {
		return false
	}
	return strings.HasPrefix(c, "http://") || strings.HasPrefix(c, "https://")
}

// ShellInvocation wraps a manifest command for the given OS.
func ShellInvocation(goos, command string) (name string, args []string) {
	if goos == "windows" {
		return "powershell.exe", []string{"-NoProfile", "-NonInteractive", "-Command", command}
	}
	return "/bin/sh", []string{"-c", command}
}

// ModelName derives the OpenAI model id for a bundle ref (the bundle name).
func ModelName(ref string) string {
	ref = strings.TrimSpace(ref)
	if i := strings.LastIndex(ref, ":"); i > 0 {
		ref = ref[:i]
	}
	if i := strings.LastIndex(ref, "/"); i >= 0 {
		return ref[i+1:]
	}
	return ref
}

func normalizeOS(goos string) string {
	if goos == "" {
		goos = runtime.GOOS
	}
	return strings.ToLower(strings.TrimSpace(goos))
}

func normalizeArch(goarch string) string {
	switch strings.ToLower(strings.TrimSpace(goarch)) {
	case "", "amd64":
		return "x86_64"
	case "arm64", "aarch64":
		return "arm64"
	}
	return strings.ToLower(strings.TrimSpace(goarch))
}

func containsFold(values []string, want string) bool {
	for _, v := range values {
		if strings.EqualFold(strings.TrimSpace(v), want) {
			return true
		}
	}
	return false
}
