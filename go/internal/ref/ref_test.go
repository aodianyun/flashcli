package ref

import "testing"

func TestParseFlashHubRef(t *testing.T) {
	p, err := Parse("flashcli-bundle/pi05_libero:1.0.4")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Local || p.Namespace != "flashcli-bundle" || p.Name != "pi05_libero" || p.Version != "1.0.4" {
		t.Fatalf("unexpected: %+v", p)
	}
}

func TestParseVariant(t *testing.T) {
	p, err := Parse("flashcli-bundle/qwen_nvfp4:1.0.1@qwen36")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Variant != "qwen36" || p.Name != "qwen_nvfp4" {
		t.Fatalf("unexpected: %+v", p)
	}
}

func TestParseLocal(t *testing.T) {
	p, err := Parse("bundles/qwen_nvfp4@qwen36")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if !p.Local || p.Name != "qwen_nvfp4" || p.Variant != "qwen36" {
		t.Fatalf("unexpected: %+v", p)
	}
}

func TestIsFlashHub(t *testing.T) {
	if !IsFlashHub("flashcli-bundle/pi05_libero:1.0.4") {
		t.Fatal("expected FlashHub ref")
	}
	if IsFlashHub("bundles/qwen_nvfp4@qwen36") {
		t.Fatal("expected local path")
	}
}

func TestEmptyVariantRejected(t *testing.T) {
	if _, err := Parse("foo/bar:1.0.0@"); err == nil {
		t.Fatal("expected error for empty variant")
	}
}
