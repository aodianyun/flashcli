// Package inferexec builds the argv/env for the bundle infer process and
// re-execs into it. Mirrors src/flashcli/runtime/reexec.py.
package inferexec

import (
	"strings"
	"syscall"
)

// BuildArgv returns the infer command:
//
//	<python> -m flashcli_bundle.infer <capability> <rest...>
func BuildArgv(python, capability string, rest []string) []string {
	argv := make([]string, 0, 3+len(rest))
	argv = append(argv, python, "-m", "flashcli_bundle.infer", capability)
	argv = append(argv, rest...)
	return argv
}

// BuildEnv returns env with the infer-process overrides applied.
func BuildEnv(base []string, runtimeID, bundleRoot, venvRoot string) []string {
	env := make([]string, 0, len(base)+8)
	for _, kv := range base {
		key := kv
		if i := strings.IndexByte(kv, '='); i >= 0 {
			key = kv[:i]
		}
		switch key {
		case "PYTHONPATH", "PYTHONSAFEPATH",
			"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE",
			"FLASHCLI_IN_BUNDLE_VENV", "FLASHCLI_RUNTIME_ID", "FLASHCLI_BUNDLE_ROOT",
			"VIRTUAL_ENV":
			continue
		}
		env = append(env, kv)
	}
	env = append(env,
		"HF_HUB_OFFLINE=1",
		"TRANSFORMERS_OFFLINE=1",
		"HF_DATASETS_OFFLINE=1",
		"FLASHCLI_IN_BUNDLE_VENV=1",
		"FLASHCLI_RUNTIME_ID="+runtimeID,
		"FLASHCLI_BUNDLE_ROOT="+bundleRoot,
		"VIRTUAL_ENV="+venvRoot,
	)
	return env
}

// Exec replaces the current process with the infer interpreter.
func Exec(python string, argv, env []string) error {
	return syscall.Exec(python, argv, env)
}
