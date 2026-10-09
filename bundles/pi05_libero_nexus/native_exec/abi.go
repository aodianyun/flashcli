// Package main — self-contained ABI driver for the pi05_libero_nexus
// native-exec server.
//
// This is bundle-owned code (not part of the host). It carries its own
// model-runtime binding so the bundle's native-exec process is fully
// independent: the host only spawns the binary and speaks NDJSON/HTTP.
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"strconv"
	"strings"
	"unsafe"

	"github.com/ebitengine/purego"
)

// ---- placeholders (mirrors the manifest native-config placeholder set) ----

type Placeholders struct {
	Checkpoint string
	BundleRoot string
	ModelsDir  string
	RuntimeDir string
	Tokenizer  string
	Variant    string
	Extra      map[string]string
	Options    map[string]string
}

func (p Placeholders) Resolve(s string) string {
	repl := map[string]string{
		"checkpoint":  p.Checkpoint,
		"bundle_root": p.BundleRoot,
		"models_dir":  p.ModelsDir,
		"runtime_dir": p.RuntimeDir,
		"tokenizer":   p.Tokenizer,
		"variant":     p.Variant,
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

// ---- native-abi spec (Nexus embedded session lane) ----

type SessionSpec struct {
	ProducerLibrary string
	SessionLibrary  string
	LoaderSymbol    string
	Preload         []string
	Config          map[string]any
}

func sessionSpecFromMap(raw map[string]any) (SessionSpec, error) {
	lib := strings.TrimSpace(stringValue(raw["library"]))
	if lib == "" {
		return SessionSpec{}, errors.New("config.library is required")
	}
	sess := strings.TrimSpace(stringValue(raw["session_library"]))
	if sess == "" {
		return SessionSpec{}, errors.New("config.session_library is required")
	}
	loader := strings.TrimSpace(stringValue(raw["loader_symbol"]))
	if loader == "" {
		loader = "flashrt_loaded_model_open"
	}
	return SessionSpec{
		ProducerLibrary: lib,
		SessionLibrary:  sess,
		LoaderSymbol:    loader,
		Preload:         toStringList(raw["preload"]),
		Config:          mapValue(raw["config"]),
	}, nil
}

type frtImageView struct {
	StructSize  uint32
	PixelFormat uint32
	Data        unsafe.Pointer
	Bytes       uint64
	Width       int32
	Height      int32
	StrideBytes int32
	Reserved    uint32
	TimestampNS uint64
}

type nexusEmbeddedConfig struct {
	StructSize uint32
	Model      uintptr
	Flags      uint32
}

type nexusEmbeddedTickResult struct {
	StructSize uint32
	ChunkID    uint64
	LatencyMS  float64
	Written    uint64
}

// Session is one embedded session over an adopted model runtime.
type Session struct {
	handles     []uintptr
	loader      uintptr
	sess        uintptr
	loaderClose func(uintptr)
	embClose    func(uintptr)
	embSetInput func(uintptr, *byte, unsafe.Pointer, uint64, int32) int32
	embTick     func(uintptr, *nexusEmbeddedTickResult) int32
	embGetOut   func(uintptr, *byte, unsafe.Pointer, uint64, *uint64, int32) int32
	embSnapshot func(uintptr, *byte) int32
	embRestore  func(uintptr, *byte) int32
	embLastErr  func(uintptr) *byte
	embFinger   func(uintptr) uint64
	embIdentity func(uintptr) *byte
}

func openSession(spec SessionSpec, ph Placeholders) (*Session, error) {
	producerPath, err := resolveGlob(ph, spec.ProducerLibrary)
	if err != nil {
		return nil, err
	}
	sessPath, err := resolveGlob(ph, spec.SessionLibrary)
	if err != nil {
		return nil, err
	}
	s := &Session{}
	for _, pattern := range spec.Preload {
		path, err := resolveGlob(ph, pattern)
		if err != nil {
			s.Close()
			return nil, err
		}
		h, err := purego.Dlopen(path, purego.RTLD_NOW|purego.RTLD_GLOBAL)
		if err != nil {
			s.Close()
			return nil, fmt.Errorf("dlopen %s: %w", path, err)
		}
		s.handles = append(s.handles, h)
	}
	sessHandle, err := purego.Dlopen(sessPath, purego.RTLD_NOW|purego.RTLD_GLOBAL)
	if err != nil {
		s.Close()
		return nil, fmt.Errorf("dlopen %s: %w", sessPath, err)
	}
	s.handles = append(s.handles, sessHandle)

	var openFn func(*byte, *byte, *unsafe.Pointer, *unsafe.Pointer) int32
	if err := registerFunc(&openFn, sessHandle, spec.LoaderSymbol); err != nil {
		s.Close()
		return nil, err
	}
	registerFunc(&s.loaderClose, sessHandle, "flashrt_loaded_model_close")

	configJSON, err := resolveConfig(spec.Config, ph)
	if err != nil {
		s.Close()
		return nil, err
	}
	cProd := append([]byte(producerPath), 0)
	cCfg := append([]byte(configJSON), 0)
	var loader, model unsafe.Pointer
	if rc := openFn(&cProd[0], &cCfg[0], &loader, &model); rc != 0 {
		s.Close()
		return nil, fmt.Errorf("%s(%s) returned %d", spec.LoaderSymbol, filepath.Base(producerPath), rc)
	}
	s.loader = uintptr(loader)

	cfg := nexusEmbeddedConfig{StructSize: uint32(unsafe.Sizeof(nexusEmbeddedConfig{})), Model: uintptr(model)}
	var embOpen func(*nexusEmbeddedConfig, *unsafe.Pointer) int32
	if err := registerFunc(&embOpen, sessHandle, "nexus_embedded_open"); err != nil {
		s.Close()
		return nil, err
	}
	var sess unsafe.Pointer
	if rc := embOpen(&cfg, &sess); rc != 0 {
		s.Close()
		return nil, fmt.Errorf("nexus_embedded_open returned %d", rc)
	}
	s.sess = uintptr(sess)

	registerFunc(&s.embClose, sessHandle, "nexus_embedded_close")
	registerFunc(&s.embSetInput, sessHandle, "nexus_embedded_set_input")
	registerFunc(&s.embTick, sessHandle, "nexus_embedded_tick")
	registerFunc(&s.embGetOut, sessHandle, "nexus_embedded_get_output")
	registerFunc(&s.embSnapshot, sessHandle, "nexus_embedded_snapshot")
	registerFunc(&s.embRestore, sessHandle, "nexus_embedded_restore")
	registerFunc(&s.embLastErr, sessHandle, "nexus_embedded_last_error")
	registerFunc(&s.embFinger, sessHandle, "nexus_embedded_fingerprint")
	registerFunc(&s.embIdentity, sessHandle, "nexus_embedded_identity")
	return s, nil
}

func (s *Session) Close() error {
	if s.sess != 0 && s.embClose != nil {
		s.embClose(s.sess)
		s.sess = 0
	}
	if s.loader != 0 && s.loaderClose != nil {
		s.loaderClose(s.loader)
		s.loader = 0
	}
	for i := len(s.handles) - 1; i >= 0; i-- {
		_ = purego.Dlclose(s.handles[i])
	}
	s.handles = nil
	return nil
}

func (s *Session) SetInput(port string, data unsafe.Pointer, bytes uint64) error {
	c := append([]byte(port), 0)
	if rc := s.embSetInput(s.sess, &c[0], data, bytes, -1); rc != 0 {
		return fmt.Errorf("set_input %s failed (%d)", port, rc)
	}
	return nil
}

func (s *Session) SetText(port, text string) error {
	if text == "" {
		return s.SetInput(port, nil, 0)
	}
	b := []byte(text)
	return s.SetInput(port, unsafe.Pointer(&b[0]), uint64(len(b)))
}

func (s *Session) SetF32(port string, values []float32) error {
	if len(values) == 0 {
		return s.SetInput(port, nil, 0)
	}
	return s.SetInput(port, unsafe.Pointer(&values[0]), uint64(len(values))*4)
}

func (s *Session) SetFrames(port string, frames []Frame) error {
	if len(frames) == 0 {
		return s.SetInput(port, nil, 0)
	}
	views := make([]frtImageView, len(frames))
	for i := range frames {
		f := &frames[i]
		stride := f.Stride
		if stride == 0 {
			stride = f.Width * 3
		}
		views[i] = frtImageView{
			StructSize:  uint32(unsafe.Sizeof(frtImageView{})),
			PixelFormat: 0,
			Data:        unsafe.Pointer(&f.RGB[0]),
			Bytes:       uint64(len(f.RGB)),
			Width:       int32(f.Width),
			Height:      int32(f.Height),
			StrideBytes: int32(stride),
		}
	}
	return s.SetInput(port, unsafe.Pointer(&views[0]), uint64(len(views))*uint64(unsafe.Sizeof(frtImageView{})))
}

func (s *Session) Tick() error {
	res := nexusEmbeddedTickResult{StructSize: uint32(unsafe.Sizeof(nexusEmbeddedTickResult{}))}
	if rc := s.embTick(s.sess, &res); rc != 0 {
		return fmt.Errorf("tick failed (%d): %s", rc, s.LastError())
	}
	return nil
}

func (s *Session) GetF32(port string, capacity int) ([]float32, error) {
	if capacity <= 0 {
		capacity = 1
	}
	buf := make([]float32, capacity)
	c := append([]byte(port), 0)
	var written uint64
	rc := s.embGetOut(s.sess, &c[0], unsafe.Pointer(&buf[0]), uint64(capacity)*4, &written, -1)
	if rc != 0 {
		return nil, fmt.Errorf("get_output %s failed (%d): %s", port, rc, s.LastError())
	}
	n := int(written / 4)
	if n > capacity {
		n = capacity
	}
	return buf[:n], nil
}

func (s *Session) Fingerprint() uint64 {
	if s.sess == 0 || s.embFinger == nil {
		return 0
	}
	return s.embFinger(s.sess)
}

func (s *Session) Identity() string {
	if s.sess == 0 || s.embIdentity == nil {
		return ""
	}
	return cString(s.embIdentity(s.sess))
}

func (s *Session) LastError() string {
	if s.sess == 0 || s.embLastErr == nil {
		return ""
	}
	return cString(s.embLastErr(s.sess))
}

// ---- generic IO descriptors ----

type InputSpec struct {
	Port, Kind, Option string
	Dim, Views         int
	Size               [2]int
}

type OutputSpec struct {
	Port  string
	Shape []int
}

func (o OutputSpec) Elements() int {
	n := 1
	for _, d := range o.Shape {
		if d > 0 {
			n *= d
		}
	}
	return n
}

func inputSpecs(raw map[string]any) []InputSpec {
	var out []InputSpec
	for _, item := range anyList(raw["inputs"]) {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		s := InputSpec{Port: strField(m, "port"), Kind: strField(m, "kind"), Option: strField(m, "option"), Dim: intField(m, "dim")}
		if size := anyList(m["size"]); len(size) == 2 {
			s.Size = [2]int{toInt(size[0]), toInt(size[1])}
		}
		s.Views = intField(m, "views")
		if s.Port != "" && s.Kind != "" {
			if s.Option == "" {
				s.Option = s.Port
			}
			out = append(out, s)
		}
	}
	return out
}

func outputSpec(raw map[string]any) OutputSpec {
	m, ok := raw["output"].(map[string]any)
	if !ok {
		return OutputSpec{}
	}
	s := OutputSpec{Port: strField(m, "port")}
	for _, d := range anyList(m["shape"]) {
		s.Shape = append(s.Shape, toInt(d))
	}
	return s
}

type Frame struct {
	RGB                   []byte
	Width, Height, Stride int
}

type InputValues struct {
	Text map[string]string
	F32  map[string][]float32
	RGB  map[string][]Frame
}

func (s *Session) Apply(specs []InputSpec, v InputValues) error {
	for _, in := range specs {
		switch in.Kind {
		case "text":
			if text, ok := v.Text[in.Option]; ok {
				if err := s.SetText(in.Port, text); err != nil {
					return err
				}
			}
		case "f32":
			vals, ok := v.F32[in.Option]
			if !ok || len(vals) == 0 {
				if in.Dim <= 0 {
					continue
				}
				vals = make([]float32, in.Dim)
			}
			if err := s.SetF32(in.Port, vals); err != nil {
				return err
			}
		case "rgb8":
			frames, ok := v.RGB[in.Option]
			if !ok || len(frames) == 0 {
				if in.Views <= 0 {
					continue
				}
				frames = zeroFrames(in.Views, in.Size)
			}
			if err := s.SetFrames(in.Port, frames); err != nil {
				return err
			}
		default:
			return fmt.Errorf("unknown input kind %q for port %s", in.Kind, in.Port)
		}
	}
	return nil
}

func zeroFrames(views int, size [2]int) []Frame {
	h, w := size[0], size[1]
	if h <= 0 || w <= 0 {
		return nil
	}
	rgb := make([]byte, h*w*3)
	out := make([]Frame, views)
	for i := range out {
		out[i] = Frame{RGB: rgb, Width: w, Height: h, Stride: w * 3}
	}
	return out
}

// ---- config resolution (placeholders + numeric coercion) ----

func resolveConfig(config map[string]any, ph Placeholders) (string, error) {
	if config == nil {
		return "{}", nil
	}
	blob, err := json.Marshal(resolveValue(config, ph))
	if err != nil {
		return "", err
	}
	return string(blob), nil
}

func resolveValue(v any, ph Placeholders) any {
	switch t := v.(type) {
	case string:
		out := ph.Resolve(t)
		if strings.Contains(t, "{") {
			if i, err := strconv.ParseInt(out, 10, 64); err == nil {
				return i
			}
			if f, err := strconv.ParseFloat(out, 64); err == nil {
				return f
			}
		}
		return out
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

// ---- helpers ----

func registerFunc(fptr any, handle uintptr, name string) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("resolve symbol %s: %v", name, r)
		}
	}()
	purego.RegisterLibFunc(fptr, handle, name)
	return nil
}

func resolveGlob(ph Placeholders, pattern string) (string, error) {
	resolved := ph.Resolve(pattern)
	if resolved == "" {
		return "", errors.New("empty library pattern")
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

func cString(p *byte) string {
	if p == nil {
		return ""
	}
	n := 0
	for *(*byte)(unsafe.Add(unsafe.Pointer(p), n)) != 0 {
		n++
	}
	return string(unsafe.Slice(p, n))
}

func stringValue(v any) string {
	s, _ := v.(string)
	return s
}

func toStringList(v any) []string {
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

func anyList(v any) []any {
	l, _ := v.([]any)
	return l
}

func strField(m map[string]any, k string) string {
	s, _ := m[k].(string)
	return s
}

func intField(m map[string]any, k string) int { return toInt(m[k]) }

func toInt(v any) int {
	switch t := v.(type) {
	case float64:
		return int(t)
	case int:
		return t
	case int64:
		return int(t)
	}
	return 0
}
