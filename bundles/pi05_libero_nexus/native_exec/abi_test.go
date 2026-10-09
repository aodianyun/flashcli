package main

import (
	"encoding/base64"
	"testing"
)

func TestSessionSpecFromMap(t *testing.T) {
	spec, err := sessionSpecFromMap(map[string]any{
		"library":         "L",
		"session_library": "S",
		"preload":         []any{"p1", "p2"},
		"config":          map[string]any{"io": "native_v2"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if spec.ProducerLibrary != "L" || spec.SessionLibrary != "S" || spec.LoaderSymbol != "flashrt_loaded_model_open" {
		t.Fatalf("spec = %+v", spec)
	}
	if len(spec.Preload) != 2 || spec.Config["io"] != "native_v2" {
		t.Fatalf("spec = %+v", spec)
	}
	if _, err := sessionSpecFromMap(map[string]any{"session_library": "S"}); err == nil {
		t.Fatal("missing library should error")
	}
	if _, err := sessionSpecFromMap(map[string]any{"library": "L"}); err == nil {
		t.Fatal("missing session_library should error")
	}
}

func TestSpecsAndOutput(t *testing.T) {
	cfg := map[string]any{
		"inputs": []any{
			map[string]any{"port": "prompt", "kind": "text", "option": "prompt"},
			map[string]any{"port": "state", "kind": "f32", "option": "state", "dim": float64(8)},
		},
		"output": map[string]any{"port": "actions", "shape": []any{float64(10), float64(7)}},
	}
	specs := inputSpecs(cfg)
	if len(specs) != 2 || specs[1].Dim != 8 {
		t.Fatalf("specs = %+v", specs)
	}
	if out := outputSpec(cfg); out.Port != "actions" || out.Elements() != 70 {
		t.Fatalf("output = %+v elem=%d", out, out.Elements())
	}
}

func TestValuesFromPayload(t *testing.T) {
	specs := []InputSpec{
		{Port: "prompt", Kind: "text", Option: "prompt"},
		{Port: "state", Kind: "f32", Option: "state", Dim: 8},
		{Port: "images", Kind: "rgb8", Option: "image", Views: 1},
	}
	img := base64.StdEncoding.EncodeToString(make([]byte, 224*224*3))
	v := valuesFromPayload(specs, map[string]any{
		"prompt": "hi",
		"state":  []any{float64(1), float64(2)},
		"image":  []any{map[string]any{"width": float64(224), "height": float64(224), "data": img}},
	})
	if v.Text["prompt"] != "hi" || len(v.F32["state"]) != 2 || len(v.RGB["image"]) != 1 {
		t.Fatalf("values = %+v", v)
	}
	if v.RGB["image"][0].Width != 224 {
		t.Fatalf("frame = %+v", v.RGB["image"][0])
	}
	// string forms
	if got := toF32s("1, 2.5"); len(got) != 2 || got[1] != 2.5 {
		t.Fatalf("toF32s string = %v", got)
	}
}
