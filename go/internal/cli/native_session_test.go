package cli

import (
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/nativeabi"
)

func variantCLIManifest(t *testing.T) *manifest.Manifest {
	t.Helper()
	data := map[string]any{
		"format": "flashcli-model-bundle", "format_version": float64(3), "protocol_version": float64(1),
		"runtime_abi_version": float64(1), "exec_protocol_version": float64(1),
		"name": "t",
		"entry": map[string]any{
			"kind":  "native-abi",
			"run":   map[string]any{"kind": "native-abi"},
			"serve": map[string]any{"kind": "native-abi"},
		},
		"variants": map[string]any{
			"abi": map[string]any{
				"run_options": []any{map[string]any{"name": "num_views", "default": float64(2), "help": "h"}},
			},
			"exec": map[string]any{
				"entry":       map[string]any{"kind": "native-exec", "run": map[string]any{"kind": "native-exec"}},
				"run_options": []any{map[string]any{"name": "num_views", "default": float64(4), "help": "h"}},
			},
		},
		"runtime": map[string]any{"sm120-cu130-linux-x86_64": "runtime/sm120-cu130-linux-x86_64"},
	}
	m, err := manifest.LoadData(data, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func TestParseFloats(t *testing.T) {
	got := parseFloats("1, 2.5, x, 3")
	if len(got) != 3 || got[0] != 1 || got[1] != 2.5 || got[2] != 3 {
		t.Fatalf("parseFloats = %v", got)
	}
}

func TestOptionDefaultsVariantAware(t *testing.T) {
	m := variantCLIManifest(t)
	if v := optionDefaults(m, "run", "abi")["num_views"]; v != "2" {
		t.Fatalf("abi num_views = %q", v)
	}
	if v := optionDefaults(m, "run", "exec")["num_views"]; v != "4" {
		t.Fatalf("exec num_views = %q", v)
	}
}

func TestMergeOptionsAndIntOption(t *testing.T) {
	def := map[string]string{"a": "1", "b": "2"}
	got := mergeOptions(def, map[string]any{"b": 9, "c": true})
	if got["a"] != "1" || got["b"] != "9" || got["c"] != "true" {
		t.Fatalf("mergeOptions = %v", got)
	}
	if intOption(got, "a", 0) != 1 || intOption(got, "missing", 7) != 7 {
		t.Fatalf("intOption wrong")
	}
}

func TestHelpListsVariants(t *testing.T) {
	m := variantCLIManifest(t)
	if h := bundleHelp(m, "run", ""); !strings.Contains(h, "Variants: abi, exec") {
		t.Fatalf("help missing variant list:\n%s", h)
	}
	if h := bundleHelp(m, "run", "exec"); !strings.Contains(h, "selected: exec") {
		t.Fatalf("help missing selected variant:\n%s", h)
	}
	if got := bundleOptionSpecs(m, "run", "exec"); len(got) != 1 || got[0].Name != "num_views" {
		t.Fatalf("exec option specs = %+v", got)
	}
}

func TestInputValuesFromOptionsAndRequest(t *testing.T) {
	e := &manifest.EntrySpec{Native: map[string]any{
		"inputs": []any{
			map[string]any{"port": "prompt", "kind": "text", "option": "prompt"},
			map[string]any{"port": "state", "kind": "f32", "option": "state", "dim": float64(8)},
			map[string]any{"port": "images", "kind": "rgb8", "option": "image", "views": float64(1)},
		},
	}}
	specs := nativeabi.InputSpecs(e)

	ov := inputValuesFromOptions(specs, map[string]string{"prompt": "hi", "state": "1,2"})
	if ov.Text["prompt"] != "hi" || len(ov.F32["state"]) != 2 {
		t.Fatalf("options values = %+v", ov)
	}

	img := base64.StdEncoding.EncodeToString(make([]byte, 224*224*3))
	body := map[string]json.RawMessage{
		"prompt": json.RawMessage(`"go"`),
		"state":  json.RawMessage(`[1,2,3]`),
		"image":  json.RawMessage(`[{"width":224,"height":224,"data":"` + img + `"}]`),
	}
	rv, err := inputValuesFromRequest(specs, body)
	if err != nil {
		t.Fatal(err)
	}
	if rv.Text["prompt"] != "go" || len(rv.F32["state"]) != 3 || len(rv.RGB["image"]) != 1 {
		t.Fatalf("request values = %+v", rv)
	}
}
