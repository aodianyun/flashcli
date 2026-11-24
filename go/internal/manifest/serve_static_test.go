package manifest

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func staticTestManifest(t *testing.T, body string, caps []string, set bool) (*Manifest, string) {
	t.Helper()
	dir := t.TempDir()
	file := filepath.Join(dir, "serve.py")
	if err := os.WriteFile(file, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	spec := &EntrySpec{
		Kind: "python", Mode: "engine", Module: "serve", Attr: "ServeEngine",
		Capabilities: caps, CapabilitiesSet: set,
	}
	return &Manifest{Root: dir, EntryServe: spec}, file
}

func staticConcurrencyManifest(t *testing.T, body string, caps []string, concurrency int) *Manifest {
	t.Helper()
	m, _ := staticTestManifest(t, body, caps, true)
	m.EntryServe.Concurrency = concurrency
	m.EntryServe.ConcurrencySet = true
	return m
}

const staticBase = `class ServeEngine:
    model_id = "m"
    def load(self, checkpoint, preset, **options): pass
    def warmup(self, spec=None): pass
`

const staticSyncChat = staticBase + `    def chat(self, request): return None
    def chat_stream(self, request): yield None
`

const staticAsyncChat = staticBase + `    async def chat(self, request): return None
    async def chat_stream(self, request): yield None
`

const staticAsyncAliases = staticBase + `    async def chat_async(self, request): return None
    async def chat_stream_async(self, request): yield None
`

func TestValidateServeMethodsMissing(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	m, _ := staticTestManifest(t, staticBase, []string{"openai.embeddings"}, true)
	errs := ValidateServeMethods(m)
	if len(errs) != 1 || !strings.Contains(errs[0], "embed") {
		t.Fatalf("errors = %v", errs)
	}

	m, _ = staticTestManifest(
		t,
		staticBase+"    def embed(self, request): pass\n",
		[]string{"openai.embeddings"},
		true,
	)
	if errs := ValidateServeMethods(m); len(errs) != 0 {
		t.Fatalf("complete engine errors = %v", errs)
	}
}

func TestValidateServeMethodsSkipsInheritedAndImported(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	inherited := "class Base: pass\n" + strings.ReplaceAll(staticBase, "class ServeEngine:", "class ServeEngine(Base):")
	m, _ := staticTestManifest(t, inherited, []string{"openai.embeddings"}, true)
	if errs := ValidateServeMethods(m); len(errs) != 0 {
		t.Fatalf("inherited class errors = %v", errs)
	}

	m, _ = staticTestManifest(
		t,
		"from somewhere import ServeEngine\n",
		[]string{"openai.embeddings"},
		true,
	)
	if errs := ValidateServeMethods(m); len(errs) != 0 {
		t.Fatalf("imported class errors = %v", errs)
	}
}

func TestValidateServeMethodsExplicitEmptyAndLegacy(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	m, _ := staticTestManifest(t, staticBase, []string{}, true)
	if errs := ValidateServeMethods(m); len(errs) != 0 {
		t.Fatalf("empty capabilities errors = %v", errs)
	}

	m, _ = staticTestManifest(t, staticBase, nil, false)
	errs := ValidateServeMethods(m)
	if len(errs) != 1 || !strings.Contains(errs[0], "chat") {
		t.Fatalf("legacy capabilities errors = %v", errs)
	}
}

func TestValidateServeMethodsSyntaxError(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	m, _ := staticTestManifest(t, "class ServeEngine(:\n", []string{}, true)
	errs := ValidateServeMethods(m)
	if len(errs) != 1 || !strings.Contains(errs[0], "line") {
		t.Fatalf("syntax errors = %v", errs)
	}
}

func TestValidateServeMethodsConcurrency(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	cases := []struct {
		name    string
		body    string
		caps    []string
		wantErr string
	}{
		{"sync chat", staticSyncChat, []string{"openai.chat"}, "async"},
		{"async chat", staticAsyncChat, []string{"openai.chat"}, ""},
		{"async aliases", staticAsyncAliases, []string{"openai.chat"}, ""},
		{
			"async chat sync stream",
			staticBase + `    async def chat(self, request): return None
    def chat_stream(self, request): yield None
`,
			[]string{"openai.chat"},
			"async",
		},
		{
			"sync speech",
			staticBase + "    def speech(self, request): return None\n",
			[]string{"openai.audio.speech"},
			"async",
		},
		{
			"async embed",
			staticBase + "    async def embed(self, request): return None\n",
			[]string{"openai.embeddings"},
			"",
		},
		{
			"sync embed",
			staticBase + "    def embed(self, request): return None\n",
			[]string{"openai.embeddings"},
			"async",
		},
		{
			"video create async",
			staticBase + `    async def create_video(self, request): return None
    def list_videos(self): return []
    def get_video(self, video_id): return {}
    def download_video(self, video_id): return b""
    def delete_video(self, video_id): return True
`,
			[]string{"openai.videos"},
			"",
		},
		{
			"video create sync",
			staticBase + `    def create_video(self, request): return None
    def list_videos(self): return []
    def get_video(self, video_id): return {}
    def download_video(self, video_id): return b""
    def delete_video(self, video_id): return True
`,
			[]string{"openai.videos"},
			"async",
		},
		{
			"realtime handler async",
			staticBase + "    async def realtime_session(self, websocket, model): pass\n",
			[]string{"openai.realtime"},
			"",
		},
		{
			"realtime handler sync",
			staticBase + "    def realtime_session(self, websocket, model): pass\n",
			[]string{"openai.realtime"},
			"async",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			errs := ValidateServeMethods(staticConcurrencyManifest(t, tc.body, tc.caps, 2))
			joined := strings.Join(errs, "\n")
			if tc.wantErr == "" {
				if len(errs) != 0 {
					t.Fatalf("unexpected errors: %v", errs)
				}
				return
			}
			if !strings.Contains(joined, tc.wantErr) {
				t.Fatalf("errors = %v, want %q", errs, tc.wantErr)
			}
		})
	}
}
