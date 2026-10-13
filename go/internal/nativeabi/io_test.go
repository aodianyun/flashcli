package nativeabi

import (
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/nativeexec"
)

func abiEntry() *manifest.EntrySpec {
	return &manifest.EntrySpec{Kind: "native-abi", Native: map[string]any{
		"inputs": []any{
			map[string]any{"port": "prompt", "kind": "text", "option": "prompt"},
			map[string]any{"port": "state", "kind": "f32", "option": "state", "dim": float64(8)},
			map[string]any{"port": "images", "kind": "rgb8", "option": "image", "views": float64(2), "size": []any{float64(224), float64(224)}},
		},
		"output": map[string]any{"port": "actions", "shape": []any{float64(10), float64(7)}},
	}}
}

func TestInputSpecsAndOutput(t *testing.T) {
	e := abiEntry()
	specs := InputSpecs(e)
	if len(specs) != 3 {
		t.Fatalf("specs = %d, want 3", len(specs))
	}
	if specs[0].Kind != "text" || specs[0].Option != "prompt" {
		t.Fatalf("spec0 = %+v", specs[0])
	}
	if specs[1].Dim != 8 {
		t.Fatalf("state dim = %d", specs[1].Dim)
	}
	if specs[2].Views != 2 || specs[2].Size != [2]int{224, 224} {
		t.Fatalf("images spec = %+v", specs[2])
	}
	out := OutputSpecFromEntry(e)
	if out.Port != "actions" || out.Elements() != 70 {
		t.Fatalf("output = %+v elements=%d", out, out.Elements())
	}
}

func TestInputSpecsEmpty(t *testing.T) {
	if got := InputSpecs(&manifest.EntrySpec{Native: map[string]any{}}); got != nil {
		t.Fatalf("want nil, got %v", got)
	}
	if got := OutputSpecFromEntry(&manifest.EntrySpec{Native: map[string]any{}}); got.Port != "" {
		t.Fatalf("want empty output, got %+v", got)
	}
}

func TestZeroFrames(t *testing.T) {
	fr := zeroFrames(2, [2]int{4, 4})
	if len(fr) != 2 || fr[0].Width != 4 || fr[0].Height != 4 || len(fr[0].RGB) != 48 {
		t.Fatalf("frames = %+v", fr)
	}
	if zeroFrames(1, [2]int{0, 0}) != nil {
		t.Fatal("bad geometry should yield nil")
	}
}

func TestResolveValueNumericCoercion(t *testing.T) {
	ph := nativeexec.Placeholders{Options: map[string]string{"num_views": "2", "stage_plan": "full"}}
	if got := resolveValue("{option:num_views}", ph); got != int64(2) {
		t.Fatalf("num_views -> %#v, want int64(2)", got)
	}
	if got := resolveValue("{option:stage_plan}", ph); got != "full" {
		t.Fatalf("stage_plan -> %#v, want string", got)
	}
	if got := resolveValue("v{option:num_views}", ph); got != "v2" {
		t.Fatalf("mixed -> %#v, want \"v2\"", got)
	}
	if got := resolveValue("keep", ph); got != "keep" {
		t.Fatalf("plain -> %#v", got)
	}
}

func TestResolveConfigJSON(t *testing.T) {
	ph := nativeexec.Placeholders{Checkpoint: "/ck", Options: map[string]string{"num_views": "2"}}
	got, err := resolveConfig(map[string]any{
		"checkpoint_path": "{checkpoint}",
		"num_views":       "{option:num_views}",
	}, ph)
	if err != nil {
		t.Fatal(err)
	}
	if got != `{"checkpoint_path":"/ck","num_views":2}` {
		t.Fatalf("config = %s", got)
	}
}
