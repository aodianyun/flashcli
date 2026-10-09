package cli

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/nativeabi"
	"github.com/aodianyun/flashcli/go/internal/nativeexec"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/postpull"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/progress"
)

// runNativeSession drives a native-abi bundle through the Nexus embedded session
// lane (native.session_library) — no Python involved. The host is model-agnostic:
// ports, payload kinds and defaults are declared by the bundle manifest.
func runNativeSession(m *manifest.Manifest, entry *manifest.EntrySpec, root, version, variant, capability string, args []string, hf hostFlags) error {
	spec, err := nativeabi.SessionFromEntry(entry)
	if err != nil {
		return err
	}
	_, rel, err := resolveRuntimeRel(m)
	if err != nil {
		return err
	}
	checkpoint, extra, env, err := resolveWeights(m, root, version, variant, hf.Quiet, hf)
	if err != nil {
		return err
	}
	for _, kv := range env {
		if i := strings.IndexByte(kv, '='); i > 0 {
			_ = os.Setenv(kv[:i], kv[i+1:])
		}
	}

	opts := mergeOptions(optionDefaults(m, capability, variant), parseFlags(args))
	tokenizer := strings.TrimSpace(os.Getenv("FLASH_RT_PALIGEMMA_TOKENIZER"))
	if tokenizer == "" {
		tokenizer = postpull.DefaultPaligemmaPath()
	}
	ph := nativeexec.Placeholders{
		Checkpoint: checkpoint,
		BundleRoot: root,
		ModelsDir:  paths.Models(),
		Preset:     m.Name,
		Variant:    variant,
		RuntimeDir: filepath.Join(root, filepath.FromSlash(rel)),
		Tokenizer:  tokenizer,
		Extra:      extra,
		Options:    opts,
	}

	sess, err := nativeabi.OpenSession(spec, ph)
	if err != nil {
		return err
	}
	defer func() { _ = sess.Close() }()

	if capability == "serve" {
		return sessionServe(sess, entry, opts)
	}
	return sessionRun(sess, entry, opts)
}

func sessionRun(sess *nativeabi.Session, entry *manifest.EntrySpec, opts map[string]string) error {
	inputs := nativeabi.InputSpecs(entry)
	out := nativeabi.OutputSpecFromEntry(entry)
	if err := sess.Apply(inputs, inputValuesFromOptions(inputs, opts)); err != nil {
		return err
	}
	if err := sess.Tick(); err != nil {
		return err
	}
	actions, err := sess.GetF32(out.Port, out.Elements())
	if err != nil {
		return err
	}
	resp := map[string]any{
		"kind":          "native-abi",
		"session":       "nexus-embedded",
		"actions_shape": out.Shape,
		"actions_flat":  len(actions),
	}
	blob, _ := json.MarshalIndent(resp, "", "  ")
	fmt.Fprintln(os.Stdout, string(blob))
	return nil
}

func sessionServe(sess *nativeabi.Session, entry *manifest.EntrySpec, opts map[string]string) error {
	host := strings.TrimSpace(opts["host"])
	if host == "" {
		host = "127.0.0.1"
	}
	port := intOption(opts, "port", 8080)
	inputs := nativeabi.InputSpecs(entry)
	out := nativeabi.OutputSpecFromEntry(entry)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, 200, map[string]any{"status": "ok"})
	})
	mux.HandleFunc("/v1/substrate", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, 200, map[string]any{
			"kind":        "native-abi",
			"session":     "nexus-embedded",
			"fingerprint": sess.Fingerprint(),
			"identity":    sess.Identity(),
		})
	})
	mux.HandleFunc("/v1/session/state", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, 200, map[string]any{"fingerprint": sess.Fingerprint(), "identity": sess.Identity()})
	})
	mux.HandleFunc("/v1/session/snapshot", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name string `json:"name"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		if req.Name == "" {
			req.Name = "default"
		}
		if err := sess.Snapshot(req.Name); err != nil {
			writeJSON(w, 500, map[string]any{"error": err.Error()})
			return
		}
		writeJSON(w, 200, map[string]any{"snapshot": req.Name})
	})
	mux.HandleFunc("/v1/session/reset/", func(w http.ResponseWriter, r *http.Request) {
		name := strings.TrimPrefix(r.URL.Path, "/v1/session/reset/")
		if name == "" {
			writeJSON(w, 400, map[string]any{"error": "capsule name required"})
			return
		}
		if err := sess.Restore(name); err != nil {
			writeJSON(w, 500, map[string]any{"error": err.Error()})
			return
		}
		writeJSON(w, 200, map[string]any{"restored": name})
	})
	act := func(w http.ResponseWriter, r *http.Request) {
		body := map[string]json.RawMessage{}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeJSON(w, 400, map[string]any{"error": "invalid JSON: " + err.Error()})
			return
		}
		vals, err := inputValuesFromRequest(inputs, body)
		if err != nil {
			writeJSON(w, 400, map[string]any{"error": err.Error()})
			return
		}
		if err := sess.Apply(inputs, vals); err != nil {
			writeJSON(w, 500, map[string]any{"error": err.Error()})
			return
		}
		if err := sess.Tick(); err != nil {
			writeJSON(w, 500, map[string]any{"error": err.Error()})
			return
		}
		actions, err := sess.GetF32(out.Port, out.Elements())
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": err.Error()})
			return
		}
		writeJSON(w, 200, map[string]any{"actions": actions, "shape": out.Shape})
	}
	mux.HandleFunc("/v1/act", act)
	mux.HandleFunc("/v1/chat/completions", act)

	addr := net.JoinHostPort(host, strconv.Itoa(port))
	srv := &http.Server{Addr: addr, Handler: mux}
	progress.Note("native serve: listening on http://%s (no Python)", addr)
	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			fmt.Fprintf(os.Stderr, "serve error: %v\n", err)
		}
	}()
	waitForSignal()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
	return nil
}

// inputValuesFromOptions resolves declared inputs from CLI options.
func inputValuesFromOptions(specs []nativeabi.InputSpec, opts map[string]string) nativeabi.InputValues {
	vals := nativeabi.InputValues{
		Text: map[string]string{},
		F32:  map[string][]float32{},
		RGB:  map[string][]nativeabi.Frame{},
	}
	for _, in := range specs {
		raw := strings.TrimSpace(opts[in.Option])
		switch in.Kind {
		case "text":
			if raw != "" {
				vals.Text[in.Option] = raw
			}
		case "f32":
			if raw != "" {
				vals.F32[in.Option] = parseFloats(raw)
			}
		case "rgb8":
			if raw != "" {
				if frames, err := loadImagePaths(raw); err == nil {
					vals.RGB[in.Option] = frames
				}
			}
		}
	}
	return vals
}

// inputValuesFromRequest resolves declared inputs from an HTTP act body, keyed
// by the option names the bundle declared.
func inputValuesFromRequest(specs []nativeabi.InputSpec, body map[string]json.RawMessage) (nativeabi.InputValues, error) {
	vals := nativeabi.InputValues{
		Text: map[string]string{},
		F32:  map[string][]float32{},
		RGB:  map[string][]nativeabi.Frame{},
	}
	for _, in := range specs {
		raw, ok := body[in.Option]
		if !ok || len(raw) == 0 {
			continue
		}
		switch in.Kind {
		case "text":
			var s string
			if err := json.Unmarshal(raw, &s); err != nil {
				return vals, fmt.Errorf("%s: %w", in.Option, err)
			}
			vals.Text[in.Option] = s
		case "f32":
			var f []float32
			if err := json.Unmarshal(raw, &f); err != nil {
				return vals, fmt.Errorf("%s: %w", in.Option, err)
			}
			vals.F32[in.Option] = f
		case "rgb8":
			var frames []struct {
				Width  int    `json:"width"`
				Height int    `json:"height"`
				Data   string `json:"data"`
			}
			if err := json.Unmarshal(raw, &frames); err != nil {
				return vals, fmt.Errorf("%s: %w", in.Option, err)
			}
			out := make([]nativeabi.Frame, 0, len(frames))
			for _, f := range frames {
				buf, err := base64.StdEncoding.DecodeString(f.Data)
				if err != nil {
					return vals, fmt.Errorf("%s: decode image: %w", in.Option, err)
				}
				out = append(out, nativeabi.Frame{RGB: buf, Width: f.Width, Height: f.Height, Stride: f.Width * 3})
			}
			vals.RGB[in.Option] = out
		}
	}
	return vals, nil
}

func loadImagePaths(raw string) ([]nativeabi.Frame, error) {
	var frames []nativeabi.Frame
	for _, p := range strings.Split(raw, ",") {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		f, err := decodeRGB8(p)
		if err != nil {
			return nil, err
		}
		frames = append(frames, f)
	}
	return frames, nil
}

func decodeRGB8(path string) (nativeabi.Frame, error) {
	f, err := os.Open(path)
	if err != nil {
		return nativeabi.Frame{}, err
	}
	defer f.Close()
	img, _, err := image.Decode(f)
	if err != nil {
		return nativeabi.Frame{}, fmt.Errorf("decode image %s: %w", path, err)
	}
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	rgb := make([]byte, w*h*3)
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			r, g, bl, _ := img.At(b.Min.X+x, b.Min.Y+y).RGBA()
			i := (y*w + x) * 3
			rgb[i] = byte(r >> 8)
			rgb[i+1] = byte(g >> 8)
			rgb[i+2] = byte(bl >> 8)
		}
	}
	return nativeabi.Frame{RGB: rgb, Width: w, Height: h, Stride: w * 3}, nil
}

func parseFloats(raw string) []float32 {
	var out []float32
	for _, p := range strings.Split(raw, ",") {
		if v, err := strconv.ParseFloat(strings.TrimSpace(p), 32); err == nil {
			out = append(out, float32(v))
		}
	}
	return out
}

// resolveRuntimeRel picks the runtime env key + manifest runtime path.
func resolveRuntimeRel(m *manifest.Manifest) (string, string, error) {
	key := ""
	if gpu := preflight.DetectGPU(); gpu != nil {
		key = preflight.ResolveRuntimeEnvKey(m.RuntimeMap(), preflight.VariantDirName(gpu, m.PythonABIOrEmpty()))
	}
	if key == "" {
		key = strings.TrimSpace(os.Getenv("FLASHCLI_RUNTIME_ENV_KEY"))
	}
	if key == "" {
		key = m.SoleRuntimeKey()
	}
	if key == "" {
		return "", "", fmt.Errorf("bundle has no matching runtime env key; set FLASHCLI_RUNTIME_ENV_KEY")
	}
	rel, ok := m.RuntimeMap()[key]
	if !ok {
		return "", "", fmt.Errorf("runtime key %q not found in manifest", key)
	}
	return key, rel, nil
}

// optionDefaults reads variant-aware run_options/serve_options defaults.
func optionDefaults(m *manifest.Manifest, capability, variant string) map[string]string {
	key := capability + "_options"
	var raw any = m.Raw[key]
	if variant != "" {
		if variants, ok := m.Raw["variants"].(map[string]any); ok {
			if block, ok := variants[variant].(map[string]any); ok {
				if v, ok := block[key]; ok {
					raw = v
				}
			}
		}
	}
	out := map[string]string{}
	items, _ := raw.([]any)
	for _, it := range items {
		obj, ok := it.(map[string]any)
		if !ok {
			continue
		}
		name, _ := obj["name"].(string)
		if name == "" {
			continue
		}
		if def, ok := obj["default"]; ok {
			out[name] = fmt.Sprintf("%v", def)
		}
	}
	return out
}

func mergeOptions(defaults map[string]string, parsed map[string]any) map[string]string {
	out := make(map[string]string, len(defaults)+len(parsed))
	for k, v := range defaults {
		out[k] = v
	}
	for k, v := range parsed {
		out[k] = fmt.Sprintf("%v", v)
	}
	return out
}

func intOption(opts map[string]string, key string, def int) int {
	if v, ok := opts[key]; ok {
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			return n
		}
	}
	return def
}

func writeJSON(w http.ResponseWriter, code int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(body)
}
