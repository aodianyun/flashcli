package host

import (
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/progress"
)

func TestFormatPullUpdate(t *testing.T) {
	got := formatPullUpdate(progress.Update{
		Stage: "weights", Detail: "Qwen/Qwen3-1.7B",
		Written: 512 * 1024 * 1024, Total: 1024 * 1024 * 1024,
		FilesDone: 3, FilesTotal: 7, Percent: 50,
	})
	for _, want := range []string{"Qwen/Qwen3-1.7B", "3/7 files", "50%"} {
		if !strings.Contains(got, want) {
			t.Fatalf("formatPullUpdate = %q, missing %q", got, want)
		}
	}

	note := formatPullUpdate(progress.Update{Stage: "note", Detail: "venv: creating torch venv", Percent: -1})
	if note != "venv: creating torch venv" {
		t.Fatalf("note = %q", note)
	}
}
