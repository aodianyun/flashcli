// Nexus embedded session driver for native-abi bundles.
//
// When a native-abi entry declares `native.session_library` (the Nexus host,
// e.g. libcapsule_nexus_flashrt-*.so), the host loads the producer DSO through
// Nexus's `flashrt_loaded_model_open`, opens a resident `nexus_embedded_session`
// over the adopted model runtime, and drives ports/stages without any Python.
//
// See docs/bundle_execution_abi.md section 7 and FlashRT-Nexus
// nexus/embedded/session.h + backends/flashrt/flashrt_model_loader.h.
package nativeabi

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"unsafe"

	"github.com/ebitengine/purego"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/nativeexec"
)

// DefaultLoaderSymbol loads+adopts a producer DSO in one call.
const DefaultLoaderSymbol = "flashrt_loaded_model_open"

// SessionSpec is a resolved Nexus-embedded native-abi spec.
type SessionSpec struct {
	ProducerLibrary string
	SessionLibrary  string
	LoaderSymbol    string
	Preload         []string
	Config          map[string]any
}

// SessionFromEntry parses entry.<cap>.native when it declares session_library.
func SessionFromEntry(e *manifest.EntrySpec) (SessionSpec, error) {
	raw := e.Native
	lib := strings.TrimSpace(stringValue(raw["library"]))
	if lib == "" {
		return SessionSpec{}, errors.New("entry.native.library is required for native-abi")
	}
	sess := strings.TrimSpace(stringValue(raw["session_library"]))
	if sess == "" {
		return SessionSpec{}, errors.New("entry.native.session_library is required for the Nexus session lane")
	}
	loader := strings.TrimSpace(stringValue(raw["loader_symbol"]))
	if loader == "" {
		loader = DefaultLoaderSymbol
	}
	return SessionSpec{
		ProducerLibrary: lib,
		SessionLibrary:  sess,
		LoaderSymbol:    loader,
		Preload:         stringList(raw["preload"]),
		Config:          mapValue(raw["config"]),
	}, nil
}

// HasSessionLibrary reports whether a native-abi entry opts into the Nexus lane.
func HasSessionLibrary(e *manifest.EntrySpec) bool {
	return strings.TrimSpace(stringValue(e.Native["session_library"])) != ""
}

// frt_image_view mirror (runtime/include/flashrt/model_runtime.h).
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

// Nexus/embedded/session.h POD mirrors.
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
	embFind     func(uintptr, *byte) int32
	embSnapshot func(uintptr, *byte) int32
	embRestore  func(uintptr, *byte) int32
	embLastErr  func(uintptr) *byte
	embFinger   func(uintptr) uint64
	embIdentity func(uintptr) *byte
}

// OpenSession loads the Nexus host + producer DSO, adopts the model runtime and
// opens a resident embedded session.
func OpenSession(spec SessionSpec, ph nativeexec.Placeholders) (*Session, error) {
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
		detail := providerErr(producerPath)
		s.Close()
		if detail != "" {
			return nil, fmt.Errorf("%s(%s) returned %d: %s", spec.LoaderSymbol, filepath.Base(producerPath), rc, detail)
		}
		return nil, fmt.Errorf("%s(%s) returned %d%s", spec.LoaderSymbol, filepath.Base(producerPath), rc, loaderErr(sessHandle))
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
	registerFunc(&s.embFind, sessHandle, "nexus_embedded_find_port")
	registerFunc(&s.embSnapshot, sessHandle, "nexus_embedded_snapshot")
	registerFunc(&s.embRestore, sessHandle, "nexus_embedded_restore")
	registerFunc(&s.embLastErr, sessHandle, "nexus_embedded_last_error")
	registerFunc(&s.embFinger, sessHandle, "nexus_embedded_fingerprint")
	registerFunc(&s.embIdentity, sessHandle, "nexus_embedded_identity")
	return s, nil
}

// Close tears down the session, loader and DSO handles.
func (s *Session) Close() error {
	if s.sess != 0 && s.embClose != nil {
		s.embClose(s.sess)
		s.sess = 0
	}
	if s.loader != 0 && s.loaderClose != nil {
		s.loaderClose(s.loader)
		s.loader = 0
	}
	var firstErr error
	for i := len(s.handles) - 1; i >= 0; i-- {
		if err := purego.Dlclose(s.handles[i]); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	s.handles = nil
	return firstErr
}

// LastError returns the session's last error string.
func (s *Session) LastError() string {
	if s.sess == 0 || s.embLastErr == nil {
		return ""
	}
	return cString(s.embLastErr(s.sess))
}

// Fingerprint returns the adopted model fingerprint.
func (s *Session) Fingerprint() uint64 {
	if s.sess == 0 || s.embFinger == nil {
		return 0
	}
	return s.embFinger(s.sess)
}

// Identity returns the adopted model identity string.
func (s *Session) Identity() string {
	if s.sess == 0 || s.embIdentity == nil {
		return ""
	}
	return cString(s.embIdentity(s.sess))
}

// HasPort reports whether a named port exists.
func (s *Session) HasPort(name string) bool {
	if s.embFind == nil {
		return false
	}
	c := append([]byte(name), 0)
	return s.embFind(s.sess, &c[0]) >= 0
}

// SetInput writes one STAGED input port (modality-specific payload).
func (s *Session) SetInput(port string, data unsafe.Pointer, bytes uint64) error {
	c := append([]byte(port), 0)
	if rc := s.embSetInput(s.sess, &c[0], data, bytes, -1); rc != 0 {
		return fmt.Errorf("set_input %s failed (%d): %s", port, rc, s.LastError())
	}
	return nil
}

// SetText writes a TEXT port.
func (s *Session) SetText(port, text string) error {
	if len(text) == 0 {
		return s.SetInput(port, nil, 0)
	}
	b := []byte(text)
	return s.SetInput(port, unsafe.Pointer(&b[0]), uint64(len(b)))
}

// SetF32 writes a STATE/TENSOR f32 port.
func (s *Session) SetF32(port string, values []float32) error {
	if len(values) == 0 {
		return s.SetInput(port, nil, 0)
	}
	return s.SetInput(port, unsafe.Pointer(&values[0]), uint64(len(values))*4)
}

// Frame is one decoded RGB8 camera view for an IMAGE port.
type Frame struct {
	RGB    []byte
	Width  int
	Height int
	Stride int
}

// SetFrames writes an IMAGE port from decoded RGB8 frames.
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
			PixelFormat: 0, // FRT_RT_PIXEL_RGB8
			Data:        unsafe.Pointer(&f.RGB[0]),
			Bytes:       uint64(len(f.RGB)),
			Width:       int32(f.Width),
			Height:      int32(f.Height),
			StrideBytes: int32(stride),
		}
	}
	return s.SetInput(port, unsafe.Pointer(&views[0]), uint64(len(views))*uint64(unsafe.Sizeof(frtImageView{})))
}

// Tick runs the declared stage DAG once.
func (s *Session) Tick() error {
	res := nexusEmbeddedTickResult{StructSize: uint32(unsafe.Sizeof(nexusEmbeddedTickResult{}))}
	if rc := s.embTick(s.sess, &res); rc != 0 {
		return fmt.Errorf("tick failed (%d): %s", rc, s.LastError())
	}
	return nil
}

// GetF32 reads an output port as float32 (capacity in elements).
func (s *Session) GetF32(port string, capacity int) ([]float32, error) {
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

// Snapshot / Restore the resident session state by name.
func (s *Session) Snapshot(name string) error {
	c := append([]byte(name), 0)
	if rc := s.embSnapshot(s.sess, &c[0]); rc != 0 {
		return fmt.Errorf("snapshot %s failed (%d): %s", name, rc, s.LastError())
	}
	return nil
}

func (s *Session) Restore(name string) error {
	c := append([]byte(name), 0)
	if rc := s.embRestore(s.sess, &c[0]); rc != 0 {
		return fmt.Errorf("restore %s failed (%d): %s", name, rc, s.LastError())
	}
	return nil
}

// providerErr returns the producer's last open error (best effort).
func providerErr(producerPath string) string {
	h, err := purego.Dlopen(producerPath, purego.RTLD_NOW|purego.RTLD_GLOBAL)
	if err != nil {
		return ""
	}
	var fn func() *byte
	if err := registerFunc(&fn, h, "frt_pi05_native_open_last_error"); err != nil || fn == nil {
		return ""
	}
	return cString(fn())
}

func loaderErr(handle uintptr) string {
	var fn func() *byte
	if err := registerFunc(&fn, handle, "flashrt_model_loader_last_error"); err != nil || fn == nil {
		return ""
	}
	if msg := cString(fn()); msg != "" {
		return ": " + msg
	}
	return ""
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
