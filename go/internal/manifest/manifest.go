// Package manifest parses flashcli-model-bundle manifests (format_version 3)
// and validates the language-agnostic execution ABI.
//
// It mirrors flashcli_bundle/manifest.py so the Go host and the Python host
// agree on what a valid bundle is. See docs/bundle_execution_abi.md.
package manifest

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/native"
)

const (
	Format              = "flashcli-model-bundle"
	FormatVersion       = 3
	ProtocolVersion     = 1
	RuntimeABIVersion   = 1
	ExecProtocolVersion = 1
	Filename            = "flashcli-bundle.json"
)

// ValidEntryKinds is the closed set of entry.kind values.
var ValidEntryKinds = map[string]bool{
	"python":      true,
	"native-exec": true,
	"native-abi":  true,
}

var nativeEntryKinds = map[string]bool{
	"native-exec": true,
	"native-abi":  true,
}

// EntrySpec is one capability block (entry.run / entry.serve) after kind and
// native-spec resolution.
type EntrySpec struct {
	Module string
	Attr   string
	Mode   string
	Kind   string
	Native map[string]any
}

// IsNative reports whether the capability uses a native backend.
func (e *EntrySpec) IsNative() bool { return nativeEntryKinds[e.Kind] }

// Manifest is a parsed bundle manifest.
type Manifest struct {
	Root         string
	Name         string
	Description  string
	Capabilities []string
	EntryRun     *EntrySpec
	EntryServe   *EntrySpec
	Raw          map[string]any
}

// Supports reports whether a capability is declared.
func (m *Manifest) Supports(capability string) bool {
	for _, c := range m.Capabilities {
		if c == capability {
			return true
		}
	}
	return false
}

// PythonABI returns the manifest python_abi (three digits, e.g. "312").
func (m *Manifest) PythonABI() (string, error) {
	abi := strings.TrimSpace(str(m.Raw["python_abi"]))
	if len(abi) != 3 || !allDigits(abi) {
		return "", fmt.Errorf("Bundle %q missing valid python_abi (expected e.g. '312')", m.Name)
	}
	return abi, nil
}

// PythonDependencies returns the raw python_dependencies block.
func (m *Manifest) PythonDependencies() map[string]any {
	deps, _ := m.Raw["python_dependencies"].(map[string]any)
	return deps
}

// RuntimeMap returns the env_key -> relative path runtime map.
func (m *Manifest) RuntimeMap() map[string]string {
	raw, _ := m.Raw["runtime"].(map[string]any)
	out := map[string]string{}
	for k, v := range raw {
		if s, ok := v.(string); ok {
			out[k] = s
		}
	}
	return out
}

// SoleRuntimeKey returns the only runtime env key, or "" when there are 0/2+.
func (m *Manifest) SoleRuntimeKey() string {
	rt := m.RuntimeMap()
	if len(rt) != 1 {
		return ""
	}
	for k := range rt {
		return k
	}
	return ""
}

// Load reads and parses flashcli-bundle.json under root.
func Load(root string) (*Manifest, error) {
	abs, err := expandUser(root)
	if err != nil {
		return nil, err
	}
	path := filepath.Join(abs, Filename)
	blob, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("Model bundle missing %s: %s", Filename, path)
		}
		return nil, err
	}
	var data map[string]any
	if err := json.Unmarshal(blob, &data); err != nil {
		return nil, fmt.Errorf("invalid %s: %w", Filename, err)
	}
	return LoadData(data, abs)
}

// LoadData parses already-decoded manifest data. root is used for messages and
// relative-path resolution only.
func LoadData(data map[string]any, root string) (*Manifest, error) {
	entryKind := "python"
	var entryNative map[string]any
	if entry, ok := data["entry"].(map[string]any); ok {
		entryKind = strings.ToLower(strings.TrimSpace(str(entry["kind"])))
		if entryKind == "" {
			entryKind = "python"
		}
		if n, ok := entry["native"].(map[string]any); ok {
			entryNative = n
		}
	}

	entryMap, _ := data["entry"].(map[string]any)
	entryRun := entrySpecFromMap(asMap(entryMap, "run"), entryKind, entryNative)
	entryServe := entrySpecFromMap(asMap(entryMap, "serve"), entryKind, entryNative)

	name := strings.TrimSpace(str(data["name"]))
	if name == "" {
		name = filepath.Base(root)
	}

	m := &Manifest{
		Root:        root,
		Name:        name,
		Description: str(data["description"]),
		EntryRun:    entryRun,
		EntryServe:  entryServe,
		Raw:         data,
	}
	if entryRun != nil {
		m.Capabilities = append(m.Capabilities, "run")
	}
	if entryServe != nil {
		m.Capabilities = append(m.Capabilities, "serve")
	}
	if err := RequireV3(m); err != nil {
		return nil, err
	}
	return m, nil
}

func asMap(parent map[string]any, key string) map[string]any {
	if parent == nil {
		return nil
	}
	m, _ := parent[key].(map[string]any)
	return m
}

func entrySpecFromMap(data map[string]any, defaultKind string, defaultNative map[string]any) *EntrySpec {
	if len(data) == 0 {
		return nil
	}
	kind := strings.ToLower(strings.TrimSpace(str(data["kind"])))
	if kind == "" {
		kind = defaultKind
	}
	native := mergeNative(defaultNative, asMap(data, "native"))
	module := strings.TrimSpace(str(data["module"]))
	attr := strings.TrimSpace(str(data["attr"]))
	mode := strings.ToLower(strings.TrimSpace(str(data["mode"])))
	if mode != "script" {
		mode = "engine"
	}
	if kind == "python" && (module == "" || attr == "") {
		return nil
	}
	return &EntrySpec{Module: module, Attr: attr, Mode: mode, Kind: kind, Native: native}
}

func mergeNative(base, override map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range base {
		out[k] = v
	}
	for k, v := range override {
		if vMap, ok := v.(map[string]any); ok {
			if baseMap, ok := out[k].(map[string]any); ok {
				out[k] = mergeNative(baseMap, vMap)
				continue
			}
		}
		out[k] = v
	}
	return out
}

// RequireV3 enforces format/format_version/protocol_version and the execution
// version axes. Mirrors Python require_v3.
func RequireV3(m *Manifest) error {
	if str(m.Raw["format"]) != Format {
		return fmt.Errorf("Unsupported bundle format: %q (expected %q)", m.Raw["format"], Format)
	}
	if v, _ := intField(m, "format_version"); v != FormatVersion {
		return fmt.Errorf("Unsupported format_version %d (expected %d). Upgrade the bundle release or use a matching flashcli version.", v, FormatVersion)
	}
	if _, ok := m.Raw["protocol_version"]; !ok {
		return fmt.Errorf("Bundle %q missing required field protocol_version (current flashcli-bundle protocol is %d)", m.Name, ProtocolVersion)
	}
	pv, err := intField(m, "protocol_version")
	if err != nil {
		return err
	}
	if pv != ProtocolVersion {
		return fmt.Errorf("Bundle %q protocol_version=%d does not match installed flashcli-bundle protocol %d. Upgrade flashcli / flashcli-bundle or republish the bundle.", m.Name, pv, ProtocolVersion)
	}
	return CheckExecutionVersions(m)
}

// RuntimeABIVersionOrNil returns the manifest runtime_abi_version, or nil.
func (m *Manifest) RuntimeABIVersionOrNil() (int, bool) {
	v, ok := optionalInt(m, "runtime_abi_version")
	return v, ok
}

// ExecProtocolVersionOrNil returns the manifest exec_protocol_version, or nil.
func (m *Manifest) ExecProtocolVersionOrNil() (int, bool) {
	v, ok := optionalInt(m, "exec_protocol_version")
	return v, ok
}

// CheckExecutionVersions raises on missing/mismatched native version axes.
func CheckExecutionVersions(m *Manifest) error {
	kinds := map[string]bool{}
	for _, spec := range []*EntrySpec{m.EntryRun, m.EntryServe} {
		if spec != nil {
			kinds[spec.Kind] = true
		}
	}
	abiVer, abiSet := m.RuntimeABIVersionOrNil()
	execVer, execSet := m.ExecProtocolVersionOrNil()

	if kinds["native-abi"] {
		if !abiSet {
			return fmt.Errorf("Bundle %q uses entry.kind=native-abi but is missing required runtime_abi_version (expected %d)", m.Name, RuntimeABIVersion)
		}
		if abiVer != RuntimeABIVersion {
			return fmt.Errorf("Bundle %q runtime_abi_version=%d does not match supported native model-runtime ABI %d. Upgrade flashcli or republish the bundle.", m.Name, abiVer, RuntimeABIVersion)
		}
	} else if abiSet {
		return fmt.Errorf("Bundle %q sets runtime_abi_version but has no native-abi entry", m.Name)
	}

	if kinds["native-exec"] {
		if !execSet {
			return fmt.Errorf("Bundle %q uses entry.kind=native-exec but is missing required exec_protocol_version (expected %d)", m.Name, ExecProtocolVersion)
		}
		if execVer != ExecProtocolVersion {
			return fmt.Errorf("Bundle %q exec_protocol_version=%d does not match supported native-exec protocol %d. Upgrade flashcli or republish the bundle.", m.Name, execVer, ExecProtocolVersion)
		}
	} else if execSet {
		return fmt.Errorf("Bundle %q sets exec_protocol_version but has no native-exec entry", m.Name)
	}
	return nil
}

// ValidateExecution returns execution-ABI validation errors (empty = ok).
// Mirrors Python validate_bundle_execution.
func ValidateExecution(m *Manifest) []string {
	var errors []string
	for _, capSpec := range []struct {
		cap  string
		spec *EntrySpec
	}{{"run", m.EntryRun}, {"serve", m.EntryServe}} {
		spec := capSpec.spec
		if spec == nil {
			continue
		}
		if !ValidEntryKinds[spec.Kind] {
			errors = append(errors, fmt.Sprintf("entry.%s.kind %q is not one of [native-abi native-exec python]", capSpec.cap, spec.Kind))
			continue
		}
		switch spec.Kind {
		case "native-exec":
			errors = append(errors, validateNativeExec(capSpec.cap, spec.Native)...)
		case "native-abi":
			errors = append(errors, validateNativeABI(capSpec.cap, spec.Native)...)
		}
	}
	if err := CheckExecutionVersions(m); err != nil {
		errors = append(errors, err.Error())
	}
	return errors
}

func validateNativeExec(cap string, native map[string]any) []string {
	var errors []string
	command, ok := native["command"].([]any)
	if !ok || len(command) == 0 {
		errors = append(errors, fmt.Sprintf("entry.%s.native.command must be a non-empty array of strings", cap))
	} else {
		for _, a := range command {
			if s, ok := a.(string); !ok || s == "" {
				errors = append(errors, fmt.Sprintf("entry.%s.native.command must be a non-empty array of strings", cap))
				break
			}
		}
	}
	transport := strings.ToLower(strings.TrimSpace(str(native["transport"])))
	if transport == "" {
		transport = "stdio"
	}
	if transport != "stdio" && transport != "http" {
		errors = append(errors, fmt.Sprintf("entry.%s.native.transport must be 'stdio' or 'http', got %q", cap, transport))
	}
	cwd := strings.TrimSpace(str(native["cwd"]))
	if cwd == "" {
		cwd = "bundle"
	}
	if cwd != "bundle" && !strings.HasPrefix(cwd, "/") {
		errors = append(errors, fmt.Sprintf("entry.%s.native.cwd must be 'bundle' or an absolute path, got %q", cap, cwd))
	}
	return errors
}

func validateNativeABI(cap string, native map[string]any) []string {
	var errors []string
	if strings.TrimSpace(str(native["library"])) == "" {
		errors = append(errors, fmt.Sprintf("entry.%s.native.library is required for native-abi", cap))
	}
	openSymbol := strings.TrimSpace(str(native["open_symbol"]))
	if openSymbol == "" {
		openSymbol = "frt_model_runtime_open_v1"
	}
	if !isCIdentifier(openSymbol) {
		errors = append(errors, fmt.Sprintf("entry.%s.native.open_symbol must be a C identifier, got %q", cap, openSymbol))
	}
	if preload, ok := native["preload"].([]any); ok {
		for _, p := range preload {
			if s, ok := p.(string); !ok || s == "" {
				errors = append(errors, fmt.Sprintf("entry.%s.native.preload must be an array of strings", cap))
				break
			}
		}
	} else if _, present := native["preload"]; present {
		errors = append(errors, fmt.Sprintf("entry.%s.native.preload must be an array of strings", cap))
	}
	return errors
}

// Validate runs structural + execution validation (no native .so probing yet).
func Validate(m *Manifest) []string {
	var errors []string
	abi := strings.TrimSpace(str(m.Raw["python_abi"]))
	if len(abi) != 3 || !allDigits(abi) {
		errors = append(errors, fmt.Sprintf("Bundle %q missing valid python_abi (expected e.g. '312')", m.Name))
	}
	if rt, ok := m.Raw["runtime"].(map[string]any); !ok || len(rt) == 0 {
		errors = append(errors, "missing runtime map (env_key → runtime/<env-key>/ path)")
	}
	for _, capSpec := range []struct {
		cap  string
		spec *EntrySpec
	}{{"run", m.EntryRun}, {"serve", m.EntryServe}} {
		spec := capSpec.spec
		if spec == nil || spec.Kind != "python" {
			continue
		}
		path := filepath.Join(m.Root, filepath.FromSlash(strings.ReplaceAll(spec.Module, ".", "/"))+".py")
		if _, err := os.Stat(path); err != nil {
			errors = append(errors, fmt.Sprintf("entry.%s module file not found: %s (module %q under %s)", capSpec.cap, path, spec.Module, m.Root))
		}
	}
	errors = append(errors, validatePythonDependencies(m)...)
	errors = append(errors, validateRuntimeSuffix(m)...)
	errors = append(errors, native.ValidateRuntimeMatrix(m.Root, m.RuntimeMap())...)
	errors = append(errors, validateWeights(m)...)
	errors = append(errors, validateOptions(m)...)
	errors = append(errors, ValidateExecution(m)...)
	errors = append(errors, validateBundleSpecifics(m)...)
	return errors
}

func isCIdentifier(s string) bool {
	if s == "" {
		return false
	}
	for i, r := range s {
		isAlpha := r == '_' || (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		isDigit := r >= '0' && r <= '9'
		if i == 0 && !isAlpha {
			return false
		}
		if !isAlpha && !isDigit {
			return false
		}
	}
	return true
}

func allDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func str(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprintf("%v", v)
}

func intField(m *Manifest, name string) (int, error) {
	v, ok := m.Raw[name]
	if !ok {
		return 0, nil
	}
	switch n := v.(type) {
	case float64:
		return int(n), nil
	case int:
		return n, nil
	case json.Number:
		i, err := n.Int64()
		return int(i), err
	default:
		return 0, fmt.Errorf("Bundle %q has invalid %s %v (expected integer)", m.Name, name, v)
	}
}

func optionalInt(m *Manifest, name string) (int, bool) {
	if _, ok := m.Raw[name]; !ok {
		return 0, false
	}
	i, err := intField(m, name)
	if err != nil {
		return 0, false
	}
	return i, true
}

func expandUser(path string) (string, error) {
	if path == "~" || strings.HasPrefix(path, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		path = filepath.Join(home, strings.TrimPrefix(path, "~/"))
	}
	return filepath.Abs(path)
}
