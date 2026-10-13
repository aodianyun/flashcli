package doctor

import "testing"

func TestRunProbes(t *testing.T) {
	checks := Run("1.2.3")
	if len(checks) == 0 {
		t.Fatal("no checks")
	}
	if checks[0].Name != "flashcli-go" || !checks[0].OK || checks[0].Detail != "1.2.3" {
		t.Fatalf("first check = %+v", checks[0])
	}
	names := map[string]bool{}
	for _, c := range checks {
		names[c.Name] = true
		if c.Name == "" || c.Detail == "" {
			t.Fatalf("incomplete check: %+v", c)
		}
	}
	for _, want := range []string{"python3", "nvidia-smi", "nvcc", "readelf"} {
		if !names[want] {
			t.Fatalf("missing probe %q", want)
		}
	}
}
