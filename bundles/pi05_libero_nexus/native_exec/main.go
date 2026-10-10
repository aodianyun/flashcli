// Command pi05_exec_server is the bundle's native-exec backend for
// pi05_libero_nexus. It is fully self-contained (no host code): the host only
// spawns this binary and speaks NDJSON (stdio) or HTTP, per
// docs/bundle_execution_abi.md §6.
package main

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
)

type stringList []string

func (s *stringList) String() string     { return strings.Join(*s, ",") }
func (s *stringList) Set(v string) error { *s = append(*s, v); return nil }

// version is injected at build time (-ldflags "-X main.version=...").
var version = "dev"

func main() {
	var (
		showVersion = flag.Bool("version", false, "Print version and exit")
		configPath  = flag.String("config", "", "ABI descriptor JSON")
		checkpoint  = flag.String("checkpoint", "", "checkpoint directory")
		runtimeDir  = flag.String("runtime-dir", "", "selected runtime/<env-key> directory")
		tokenizer   = flag.String("tokenizer", "", "tokenizer model path")
		bundleRoot  = flag.String("bundle-root", "", "bundle root (default cwd)")
		transport   = flag.String("transport", "stdio", "stdio | http")
		host        = flag.String("host", "127.0.0.1", "http bind host")
		port        = flag.Int("port", 0, "http bind port (0 = ephemeral)")
		opts        stringList
	)
	flag.Var(&opts, "opt", "option override k=v (repeatable; feeds {option:<name>})")
	flag.Parse()
	if *showVersion {
		fmt.Printf("pi05_exec_server %s\n", version)
		return
	}

	root := *bundleRoot
	if root == "" {
		root, _ = os.Getwd()
	}
	if *configPath == "" {
		fail("--config is required")
	}
	raw, err := os.ReadFile(*configPath)
	if err != nil {
		fail("read config: %v", err)
	}
	var cfg map[string]any
	if err := json.Unmarshal(raw, &cfg); err != nil {
		fail("parse config: %v", err)
	}
	spec, err := sessionSpecFromMap(cfg)
	if err != nil {
		fail("%v", err)
	}
	inputs := inputSpecs(cfg)
	out := outputSpec(cfg)

	options := map[string]string{}
	for _, kv := range opts {
		if i := strings.IndexByte(kv, '='); i > 0 {
			options[kv[:i]] = kv[i+1:]
		}
	}
	ph := Placeholders{
		Checkpoint: *checkpoint,
		BundleRoot: root,
		ModelsDir:  os.Getenv("FLASHCLI_MODELS_DIR"),
		RuntimeDir: *runtimeDir,
		Tokenizer:  *tokenizer,
		Options:    options,
	}
	sess, err := openSession(spec, ph)
	if err != nil {
		fail("open model: %v", err)
	}
	defer func() { _ = sess.Close() }()

	srv := &server{sess: sess, inputs: inputs, out: out}
	switch strings.ToLower(*transport) {
	case "http":
		srv.serveHTTP(*host, *port)
	case "stdio":
		srv.serveStdio()
	default:
		fail("unknown transport %q", *transport)
	}
}

type server struct {
	sess   *Session
	inputs []InputSpec
	out    OutputSpec
	mu     sync.Mutex
}

func (s *server) run(payload map[string]any) (map[string]any, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.sess.Apply(s.inputs, valuesFromPayload(s.inputs, payload)); err != nil {
		return nil, err
	}
	if err := s.sess.Tick(); err != nil {
		return nil, err
	}
	actions, err := s.sess.GetF32(s.out.Port, s.out.Elements())
	if err != nil {
		return nil, err
	}
	return map[string]any{"actions": actions, "shape": s.out.Shape}, nil
}

func (s *server) serveStdio() {
	fmt.Fprintln(os.Stderr, "pi05_exec_server: stdio ready")
	out := bufio.NewWriter(os.Stdout)
	writeLine(out, map[string]any{"v": 1, "op": "ready", "payload": map[string]any{"version": version}})
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 0, 1<<20), 64<<20)
	for in.Scan() {
		line := strings.TrimSpace(in.Text())
		if line == "" {
			continue
		}
		var req struct {
			V       int            `json:"v"`
			ID      int            `json:"id"`
			Op      string         `json:"op"`
			Payload map[string]any `json:"payload"`
		}
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			writeLine(out, errResp(-1, 400, "invalid JSON: "+err.Error()))
			continue
		}
		switch req.Op {
		case "shutdown":
			writeLine(out, okResp(req.ID, map[string]any{"stopped": true}))
			return
		case "health":
			writeLine(out, okResp(req.ID, map[string]any{"status": "ok"}))
		case "run":
			res, err := s.run(req.Payload)
			if err != nil {
				writeLine(out, errResp(req.ID, 500, err.Error()))
				continue
			}
			writeLine(out, okResp(req.ID, res))
		default:
			writeLine(out, errResp(req.ID, 400, "unknown op "+req.Op))
		}
	}
}

func (s *server) serveHTTP(host string, port int) {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		wj(w, 200, map[string]any{"status": "ok"})
	})
	mux.HandleFunc("/run", func(w http.ResponseWriter, r *http.Request) {
		var payload map[string]any
		_ = json.NewDecoder(r.Body).Decode(&payload)
		res, err := s.run(payload)
		if err != nil {
			wj(w, 500, map[string]any{"error": err.Error()})
			return
		}
		wj(w, 200, res)
	})
	ln, err := net.Listen("tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		fail("listen: %v", err)
	}
	addr := ln.Addr().(*net.TCPAddr)
	endpoint := fmt.Sprintf("http://%s:%d", host, addr.Port)
	fmt.Fprintln(os.Stderr, "pi05_exec_server: http", endpoint)
	fmt.Fprintf(os.Stdout, "{\"v\":1,\"op\":\"ready\",\"payload\":{\"endpoint\":%q,\"version\":%q}}\n", endpoint, version)

	srv := &http.Server{Handler: mux}
	go func() { _ = srv.Serve(ln) }()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	<-ctx.Done()
	_ = srv.Shutdown(context.Background())
}

func valuesFromPayload(specs []InputSpec, payload map[string]any) InputValues {
	vals := InputValues{Text: map[string]string{}, F32: map[string][]float32{}, RGB: map[string][]Frame{}}
	for _, in := range specs {
		v, ok := payload[in.Option]
		if !ok {
			continue
		}
		switch in.Kind {
		case "text":
			vals.Text[in.Option] = fmt.Sprintf("%v", v)
		case "f32":
			vals.F32[in.Option] = toF32s(v)
		case "rgb8":
			vals.RGB[in.Option] = toFrames(v)
		}
	}
	return vals
}

func toF32s(v any) []float32 {
	switch t := v.(type) {
	case []any:
		out := make([]float32, 0, len(t))
		for _, e := range t {
			if f, ok := e.(float64); ok {
				out = append(out, float32(f))
			}
		}
		return out
	case string:
		var out []float32
		for _, p := range strings.Split(t, ",") {
			if f, err := strconv.ParseFloat(strings.TrimSpace(p), 32); err == nil {
				out = append(out, float32(f))
			}
		}
		return out
	}
	return nil
}

func toFrames(v any) []Frame {
	switch t := v.(type) {
	case string:
		var frames []Frame
		for _, p := range strings.Split(t, ",") {
			p = strings.TrimSpace(p)
			if p == "" {
				continue
			}
			if f, err := decodeRGB8(p); err == nil {
				frames = append(frames, f)
			}
		}
		return frames
	case []any:
		var frames []Frame
		for _, e := range t {
			m, ok := e.(map[string]any)
			if !ok {
				continue
			}
			data, _ := m["data"].(string)
			buf, err := base64.StdEncoding.DecodeString(data)
			if err != nil {
				continue
			}
			w := int(toFloat(m["width"]))
			h := int(toFloat(m["height"]))
			frames = append(frames, Frame{RGB: buf, Width: w, Height: h, Stride: w * 3})
		}
		return frames
	}
	return nil
}

func toFloat(v any) float64 {
	if f, ok := v.(float64); ok {
		return f
	}
	return 0
}

func decodeRGB8(path string) (Frame, error) {
	f, err := os.Open(path)
	if err != nil {
		return Frame{}, err
	}
	defer f.Close()
	img, _, err := image.Decode(f)
	if err != nil {
		return Frame{}, err
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
	return Frame{RGB: rgb, Width: w, Height: h, Stride: w * 3}, nil
}

func writeLine(w *bufio.Writer, v map[string]any) {
	blob, _ := json.Marshal(v)
	_, _ = w.Write(blob)
	_ = w.WriteByte('\n')
	_ = w.Flush()
}

func okResp(id int, payload map[string]any) map[string]any {
	return map[string]any{"v": 1, "id": id, "ok": true, "payload": payload}
}

func errResp(id, code int, msg string) map[string]any {
	return map[string]any{"v": 1, "id": id, "ok": false, "error": map[string]any{"code": code, "message": msg}}
}

func wj(w http.ResponseWriter, code int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(body)
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "pi05_exec_server: "+format+"\n", args...)
	os.Exit(1)
}
