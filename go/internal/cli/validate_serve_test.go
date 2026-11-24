package cli

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func writeServeValidateBundle(t *testing.T, root, serve string, caps []string, concurrency any) {
	t.Helper()
	if err := os.MkdirAll(filepath.Join(root, "runtime", "test"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, "checkpoint"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "checkpoint", "model.safetensors"), []byte{}, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "serve.py"), []byte(serve), 0o644); err != nil {
		t.Fatal(err)
	}
	entry := map[string]any{
		"kind": "python", "mode": "engine", "module": "serve", "attr": "ServeEngine",
		"capabilities": caps, "concurrency": concurrency,
	}
	option := map[string]any{"name": "warmup", "type": "string", "help": "warmup", "phase": "warmup"}
	manifest := map[string]any{
		"format": "flashcli-model-bundle", "format_version": 4, "protocol_version": 1,
		"name": "serve_validate",
		"defaults": map[string]any{
			"entry":               map[string]any{"serve": entry},
			"python_abi":          "312",
			"python_dependencies": map[string]any{"torch": false, "pip": []any{}},
			"serve_options":       []any{option},
		},
		"environments": map[string]any{
			"test-linux-x86_64-py312": map[string]any{
				"runtime": "runtime/test", "serve_options": []any{option},
			},
		},
	}
	blob, _ := json.Marshal(manifest)
	if err := os.WriteFile(filepath.Join(root, "flashcli-bundle.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestBundleValidateServeMethods(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		if _, err := exec.LookPath("python"); err != nil {
			t.Skip("python interpreter not available")
		}
	}
	cases := []struct {
		name        string
		serve       string
		caps        []string
		concurrency any
		want        int
	}{
		{
			name: "async concurrency",
			serve: "class ServeEngine:\n" +
				"    model_id = 'm'\n" +
				"    def load(self, checkpoint, preset, **options): pass\n" +
				"    def warmup(self, spec=None): pass\n" +
				"    async def chat(self, request): return None\n" +
				"    async def chat_stream(self, request): yield None\n",
			caps: []string{"openai.chat"}, concurrency: 2, want: 0,
		},
		{
			name: "sync concurrency",
			serve: "class ServeEngine:\n" +
				"    model_id = 'm'\n" +
				"    def load(self, checkpoint, preset, **options): pass\n" +
				"    def warmup(self, spec=None): pass\n" +
				"    def chat(self, request): return None\n" +
				"    def chat_stream(self, request): yield None\n",
			caps: []string{"openai.chat"}, concurrency: 2, want: 1,
		},
		{
			name: "missing embed",
			serve: "class ServeEngine:\n" +
				"    model_id = 'm'\n" +
				"    def load(self, checkpoint, preset, **options): pass\n" +
				"    def warmup(self, spec=None): pass\n",
			caps: []string{"openai.embeddings"}, concurrency: 1, want: 1,
		},
		{
			name: "empty capabilities concurrency",
			serve: "class ServeEngine:\n" +
				"    model_id = 'm'\n" +
				"    def load(self, checkpoint, preset, **options): pass\n" +
				"    def warmup(self, spec=None): pass\n",
			caps: []string{}, concurrency: 2, want: 1,
		},
		{
			name: "count only concurrency",
			serve: "class ServeEngine:\n" +
				"    model_id = 'm'\n" +
				"    def load(self, checkpoint, preset, **options): pass\n" +
				"    def warmup(self, spec=None): pass\n" +
				"    def count_tokens(self, request): return 0\n",
			caps: []string{"anthropic.count_tokens"}, concurrency: 2, want: 1,
		},
		{
			name: "zero concurrency",
			serve: "class ServeEngine:\n" +
				"    model_id = 'm'\n" +
				"    def load(self, checkpoint, preset, **options): pass\n" +
				"    def warmup(self, spec=None): pass\n",
			caps: []string{"openai.chat"}, concurrency: 0, want: 1,
		},
		{
			name: "fractional concurrency",
			serve: "class ServeEngine:\n" +
				"    model_id = 'm'\n" +
				"    def load(self, checkpoint, preset, **options): pass\n" +
				"    def warmup(self, spec=None): pass\n",
			caps: []string{"openai.chat"}, concurrency: 1.5, want: 1,
		},
		{
			name:  "imported class skips static",
			serve: "from somewhere import ServeEngine\n",
			caps:  []string{"openai.embeddings"}, concurrency: 2, want: 0,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("FLASHCLI_HOME", home)
			root := filepath.Join(home, "bundle")
			writeServeValidateBundle(t, root, tc.serve, tc.caps, tc.concurrency)
			code := Main([]string{"bundle", "validate", "--skip-abi-probe", root})
			if code != tc.want {
				t.Fatalf("validate exit = %d, want %d", code, tc.want)
			}
		})
	}
}
