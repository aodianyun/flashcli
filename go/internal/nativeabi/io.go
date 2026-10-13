// Generic, model-agnostic IO descriptors for the native-abi session lane.
//
// The bundle declares, in its manifest `native` block, the ports it exposes and
// how user options map to them. The host only builds ABI payloads for the
// declared ports (per modality) — it carries no model-specific constants,
// shapes, or preprocessing. See docs/architecture.md (principle 1) and
// docs/bundle_execution_abi.md §4/§7.
package nativeabi

import (
	"fmt"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

// InputSpec maps one bundle option to one input port.
type InputSpec struct {
	Port   string // runtime port name
	Kind   string // "text" | "f32" | "rgb8"
	Option string // manifest option name carrying the value
	Dim    int    // f32 default length (bundle-declared)
	Views  int    // rgb8 placeholder view count (bundle-declared)
	Size   [2]int // rgb8 placeholder H,W (bundle-declared)
}

// OutputSpec declares the primary output port (and its shape for buffering).
type OutputSpec struct {
	Port  string
	Shape []int
}

// Elements returns the product of Shape (fallback 1).
func (o OutputSpec) Elements() int {
	n := 1
	for _, d := range o.Shape {
		if d > 0 {
			n *= d
		}
	}
	return n
}

// InputSpecs reads entry.native.inputs (array of {port,kind,option,...}).
func InputSpecs(e *manifest.EntrySpec) []InputSpec {
	var out []InputSpec
	for _, item := range anyList(e.Native["inputs"]) {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		spec := InputSpec{
			Port:   strField(m, "port"),
			Kind:   strField(m, "kind"),
			Option: strField(m, "option"),
			Dim:    intField(m, "dim"),
		}
		if size := anyList(m["size"]); len(size) == 2 {
			spec.Size = [2]int{toInt(size[0]), toInt(size[1])}
		}
		spec.Views = intField(m, "views")
		if spec.Port != "" && spec.Kind != "" {
			if spec.Option == "" {
				spec.Option = spec.Port
			}
			out = append(out, spec)
		}
	}
	return out
}

// OutputSpecFromEntry reads entry.native.output ({port,shape}).
func OutputSpecFromEntry(e *manifest.EntrySpec) OutputSpec {
	m, ok := e.Native["output"].(map[string]any)
	if !ok {
		return OutputSpec{}
	}
	spec := OutputSpec{Port: strField(m, "port")}
	for _, d := range anyList(m["shape"]) {
		spec.Shape = append(spec.Shape, toInt(d))
	}
	return spec
}

// InputValues holds resolved user inputs keyed by option name.
type InputValues struct {
	Text map[string]string
	F32  map[string][]float32
	RGB  map[string][]Frame
}

// Apply writes every declared input port using the supplied values, falling
// back to bundle-declared defaults (zeros / zero-frames) when absent.
func (s *Session) Apply(specs []InputSpec, v InputValues) error {
	for _, in := range specs {
		switch in.Kind {
		case "text":
			text, ok := v.Text[in.Option]
			if !ok {
				continue
			}
			if err := s.SetText(in.Port, text); err != nil {
				return err
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
			return fmt.Errorf("unknown native input kind %q for port %s", in.Kind, in.Port)
		}
	}
	return nil
}

// zeroFrames builds zero-filled RGB8 frames of the bundle-declared geometry.
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
