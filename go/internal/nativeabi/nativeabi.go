// Package nativeabi loads a bundle's `native-abi` model-runtime shared library
// and drives it in-process through the FlashRT frt_model_runtime_v1 face.
//
// Mirrors docs/bundle_execution_abi.md section 7. Loading is cgo-free via
// purego (dlopen + dlsym).
package nativeabi

import (
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"unsafe"

	"github.com/ebitengine/purego"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/nativeexec"
)

// DefaultOpenSymbol is the FlashRT producer factory.
const DefaultOpenSymbol = "frt_model_runtime_open_v1"

// ABIVersion mirrors FRT_MODEL_RUNTIME_ABI_VERSION.
const ABIVersion = 1

// mirrorRuntime reproduces the frt_model_runtime_v1 baseline field order to
// derive the additive-tail-safe base size at runtime. Keep in sync with
// FlashRT runtime/include/flashrt/model_runtime.h.
type mirrorVerbs struct {
	self      uintptr
	setInput  uintptr
	getOutput uintptr
	prepare   uintptr
	step      uintptr
	lastError uintptr
}

type mirrorRuntime struct {
	abiVersion     uint32
	structSize     uint32
	exp            uintptr
	ports          uintptr
	nPorts         uint64
	stages         uintptr
	nStages        uint64
	self           uintptr
	verbs          mirrorVerbs
	owner          uintptr
	retain         uintptr
	release        uintptr
	queryExtension uintptr
}

// V1BaseSize is the minimum byte prefix a v1 consumer may require
// (FRT_MODEL_RUNTIME_V1_BASE_SIZE).
var V1BaseSize = unsafe.Offsetof(mirrorRuntime{}.release) + unsafe.Sizeof(uintptr(0))

var loadedExec = map[string]bool{}

// Spec is a resolved native-abi spec.
type Spec struct {
	Library    string
	OpenSymbol string
	Preload    []string
	Config     map[string]any
}

// SpecFromEntry parses entry.<cap>.native for kind == native-abi.
func SpecFromEntry(e *manifest.EntrySpec) (Spec, error) {
	raw := e.Native
	lib := strings.TrimSpace(stringValue(raw["library"]))
	if lib == "" {
		return Spec{}, errors.New("entry.native.library is required for native-abi")
	}
	open := strings.TrimSpace(stringValue(raw["open_symbol"]))
	if open == "" {
		open = DefaultOpenSymbol
	}
	return Spec{
		Library:    lib,
		OpenSymbol: open,
		Preload:    stringList(raw["preload"]),
		Config:     mapValue(raw["config"]),
	}, nil
}

// Library is an opened model runtime.
type Library struct {
	handles    []uintptr
	symbol     string
	runtime    unsafe.Pointer
	ABIVersion uint32
	StructSize uint32
	configJSON string
	released   bool
}

// Open resolves preload + library globs, loads them RTLD_GLOBAL in order, opens
// the model runtime, and validates the v1 prefix.
func Open(spec Spec, ph nativeexec.Placeholders) (*Library, error) {
	libPath, err := resolveGlob(ph, spec.Library)
	if err != nil {
		return nil, err
	}
	closure := "libflashrt_exec"
	if strings.Contains(filepath.Base(libPath), closure) {
		if loadedExec[libPath] {
			return nil, fmt.Errorf("libflashrt_exec already loaded; only one per process is allowed")
		}
		loadedExec[libPath] = true
	}

	l := &Library{symbol: spec.OpenSymbol}
	for _, pattern := range spec.Preload {
		path, err := resolveGlob(ph, pattern)
		if err != nil {
			l.Close()
			return nil, err
		}
		handle, err := purego.Dlopen(path, purego.RTLD_NOW|purego.RTLD_GLOBAL)
		if err != nil {
			l.Close()
			return nil, fmt.Errorf("dlopen %s: %w", path, err)
		}
		l.handles = append(l.handles, handle)
	}
	handle, err := purego.Dlopen(libPath, purego.RTLD_NOW|purego.RTLD_GLOBAL)
	if err != nil {
		l.Close()
		return nil, fmt.Errorf("dlopen %s: %w", libPath, err)
	}
	l.handles = append(l.handles, handle)

	var openFn func(configJSON *byte, out *unsafe.Pointer) int32
	if err := registerFunc(&openFn, handle, spec.OpenSymbol); err != nil {
		l.Close()
		return nil, err
	}

	configJSON, err := resolveConfig(spec.Config, ph)
	if err != nil {
		l.Close()
		return nil, err
	}
	l.configJSON = configJSON
	cstr := append([]byte(configJSON), 0)

	var out unsafe.Pointer
	if rc := openFn(&cstr[0], &out); rc != 0 {
		l.Close()
		return nil, fmt.Errorf("%s returned %d", spec.OpenSymbol, rc)
	}
	if out == nil {
		l.Close()
		return nil, fmt.Errorf("%s returned a null runtime", spec.OpenSymbol)
	}
	l.runtime = out

	mr := (*mirrorRuntime)(out)
	l.ABIVersion = mr.abiVersion
	l.StructSize = mr.structSize
	if mr.abiVersion != ABIVersion {
		l.Close()
		return nil, fmt.Errorf("runtime abi_version=%d does not match supported %d", mr.abiVersion, ABIVersion)
	}
	if mr.structSize < uint32(V1BaseSize) {
		l.Close()
		return nil, fmt.Errorf("runtime struct_size=%d smaller than v1 baseline %d", mr.structSize, V1BaseSize)
	}
	return l, nil
}

// ConfigJSON returns the resolved config passed to the open symbol.
func (l *Library) ConfigJSON() string { return l.configJSON }

// Close releases the model runtime (if it declares release) and unloads libs.
func (l *Library) Close() error {
	if l.runtime != nil && !l.released {
		mr := (*mirrorRuntime)(l.runtime)
		if mr.release != 0 {
			_, _, _ = purego.SyscallN(mr.release, mr.owner)
		}
		l.released = true
	}
	var firstErr error
	for i := len(l.handles) - 1; i >= 0; i-- {
		if err := purego.Dlclose(l.handles[i]); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	l.handles = nil
	return firstErr
}

func registerFunc(fptr any, handle uintptr, name string) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("resolve symbol %s: %v", name, r)
		}
	}()
	purego.RegisterLibFunc(fptr, handle, name)
	return nil
}

func resolveGlob(ph nativeexec.Placeholders, pattern string) (string, error) {
	resolved := ph.Resolve(pattern)
	if resolved == "" {
		return "", errors.New("empty library/preload pattern")
	}
	matches, err := filepath.Glob(resolved)
	if err != nil {
		return "", err
	}
	switch len(matches) {
	case 0:
		return "", fmt.Errorf("no file matches %q", resolved)
	case 1:
		return matches[0], nil
	default:
		return "", fmt.Errorf("ambiguous pattern %q matches %d files", resolved, len(matches))
	}
}

func resolveConfig(config map[string]any, ph nativeexec.Placeholders) (string, error) {
	if config == nil {
		return "{}", nil
	}
	blob, err := json.Marshal(resolveValue(config, ph))
	if err != nil {
		return "", err
	}
	return string(blob), nil
}

func resolveValue(v any, ph nativeexec.Placeholders) any {
	switch t := v.(type) {
	case string:
		return ph.Resolve(t)
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, val := range t {
			out[k] = resolveValue(val, ph)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, val := range t {
			out[i] = resolveValue(val, ph)
		}
		return out
	default:
		return v
	}
}

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
