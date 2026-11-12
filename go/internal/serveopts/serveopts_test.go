package serveopts

import (
	"reflect"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

func TestFromManifestTopLevelAndVariant(t *testing.T) {
	m := &manifest.Manifest{Raw: map[string]any{
		"serve_options": []any{
			map[string]any{"name": "max_seq", "type": "integer", "default": float64(2048), "help": "ctx"},
			map[string]any{"name": "model_name", "type": "string", "default": "qwen3", "help": "id"},
		},
		"variants": map[string]any{
			"x": map[string]any{
				"serve_options": []any{
					map[string]any{"name": "max_seq", "flag": "seq", "type": "integer", "default": float64(4096), "help": "ctx"},
				},
			},
		},
	}}
	top := FromManifest(m, "")
	if len(top) != 2 || top[0].Flag != "max-seq" || top[0].Default != float64(2048) {
		t.Fatalf("top-level specs = %+v", top)
	}
	v := FromManifest(m, "x")
	if len(v) != 1 || v[0].Flag != "seq" || v[0].Default != float64(4096) {
		t.Fatalf("variant specs = %+v", v)
	}
}

func TestValidateAndFlags(t *testing.T) {
	specs := []Spec{
		{Name: "max_seq", Flag: "max-seq", Type: "integer"},
		{Name: "temperature", Flag: "temperature", Type: "float"},
		{Name: "enabled", Flag: "enabled", Type: "boolean"},
		{Name: "model_name", Flag: "model-name", Type: "string"},
	}
	got, err := Validate(specs, map[string]string{
		"max_seq":     " 8192 ",
		"temperature": "0.70",
		"enabled":     "YES",
		"model_name":  " my model ",
	})
	if err != nil {
		t.Fatal(err)
	}
	if got["max_seq"] != "8192" || got["temperature"] != "0.7" || got["enabled"] != "true" ||
		got["model_name"] != "my model" {
		t.Fatalf("normalized = %#v", got)
	}
	args, err := Flags(specs, got)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"--enabled", "true", "--max-seq", "8192", "--model-name", "my model", "--temperature", "0.7"}
	if !reflect.DeepEqual(args, want) {
		t.Fatalf("flags = %#v, want %#v", args, want)
	}
}

func TestValidateRejectsUnknownAndInvalid(t *testing.T) {
	specs := []Spec{{Name: "max_seq", Type: "integer"}, {Name: "enabled", Type: "boolean"}}
	if _, err := Validate(specs, map[string]string{"nope": "1"}); err == nil || !strings.Contains(err.Error(), "unknown") {
		t.Fatalf("unknown option error = %v", err)
	}
	if _, err := Validate(specs, map[string]string{"max_seq": "x"}); err == nil || !strings.Contains(err.Error(), "integer") {
		t.Fatalf("invalid int error = %v", err)
	}
	if _, err := Validate(specs, map[string]string{"enabled": "maybe"}); err == nil || !strings.Contains(err.Error(), "true or false") {
		t.Fatalf("invalid bool error = %v", err)
	}
}

func TestEmptyValueMeansDefault(t *testing.T) {
	specs := []Spec{{Name: "max_seq", Flag: "max-seq", Type: "integer"}}
	got, err := Validate(specs, map[string]string{"max_seq": ""})
	if err != nil {
		t.Fatal(err)
	}
	args, err := Flags(specs, got)
	if err != nil || len(args) != 0 {
		t.Fatalf("flags = %#v, err = %v", args, err)
	}
}

func TestHostLevelOptionsAreNotFlags(t *testing.T) {
	specs := []Spec{
		{Name: "ip", Flag: "ip", Type: "string", HostLevel: true},
		{Name: "port", Flag: "port", Type: "integer", HostLevel: true},
		{Name: "max_seq", Flag: "max-seq", Type: "integer"},
	}
	args, err := Flags(specs, map[string]string{"ip": "0.0.0.0", "port": "5000", "max_seq": "8192"})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"--max-seq", "8192"}
	if !reflect.DeepEqual(args, want) {
		t.Fatalf("flags = %#v, want %#v", args, want)
	}
}
