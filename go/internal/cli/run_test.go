package cli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

const execStub = `#!/usr/bin/env python3
import json, sys
sys.stdout.write(json.dumps({"v":1,"op":"ready","payload":{}})+"\n"); sys.stdout.flush()
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    req=json.loads(line)
    op=req.get("op")
    if op=="shutdown":
        sys.stdout.write(json.dumps({"v":1,"id":req.get("id"),"ok":True,"payload":{}})+"\n"); sys.stdout.flush(); break
    if op=="run":
        p=(req.get("payload") or {}).get("prompt","")
        sys.stdout.write(json.dumps({"v":1,"id":req.get("id"),"ok":True,"payload":{"echo":p}})+"\n"); sys.stdout.flush()
`

func writeExecBundle(t *testing.T, root string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Join(root, "bin"), 0o755); err != nil {
		t.Fatal(err)
	}
	stub := filepath.Join(root, "bin", "exec_echo")
	if err := os.WriteFile(stub, []byte(execStub), 0o755); err != nil {
		t.Fatal(err)
	}
	data := map[string]any{
		"format": "flashcli-model-bundle", "format_version": 3, "protocol_version": 1,
		"exec_protocol_version": 1, "name": "demo_exec", "python_abi": "310",
		"entry": map[string]any{
			"kind":   "native-exec",
			"native": map[string]any{"command": []any{"bin/exec_echo"}, "transport": "stdio"},
			"run":    map[string]any{"kind": "native-exec"},
			"serve":  map[string]any{"kind": "native-exec"},
		},
		"run_options":   []any{map[string]any{"name": "prompt", "type": "string", "default": "hi", "help": "h", "phase": "predict"}},
		"serve_options": []any{map[string]any{"name": "prompt", "type": "string", "default": "hi", "help": "h", "phase": "predict"}},
		"weights":       map[string]any{"source": "huggingface", "repo": "org/model", "revision": "main"},
		"runtime":       map[string]any{"sm89-cu124-linux-x86_64-py310": "runtime/x"},
	}
	blob, _ := json.Marshal(data)
	if err := os.WriteFile(filepath.Join(root, "flashcli-bundle.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	sub := filepath.Join(root, "runtime", "x", "substrate")
	if err := os.MkdirAll(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(sub, "libdemo.so"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestRunNativeExecLocal(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("FLASHCLI_MODELS_DIR", filepath.Join(home, "models"))
	t.Setenv("FLASHCLI_SKIP_PREFLIGHT", "1")
	t.Setenv("FLASHCLI_SKIP_WEIGHTS", "1")

	bundle := filepath.Join(home, "demo_exec")
	writeExecBundle(t, bundle)

	if code := Main([]string{"run", bundle, "--prompt", "hello"}); code != 0 {
		t.Fatalf("run exit = %d", code)
	}
}

func TestBundleValidateExec(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundle := filepath.Join(home, "demo_exec")
	writeExecBundle(t, bundle)
	if code := Main([]string{"bundle", "validate", bundle}); code != 0 {
		t.Fatalf("validate exit = %d", code)
	}
}
