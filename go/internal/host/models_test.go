package host

import "testing"

func TestEmptyCache(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	models, err := ListModels()
	if err != nil {
		t.Fatal(err)
	}
	if len(models) != 0 {
		t.Fatalf("models=%v", models)
	}
	areas := Storage()
	if len(areas) == 0 {
		t.Fatal("expected storage areas")
	}
}
