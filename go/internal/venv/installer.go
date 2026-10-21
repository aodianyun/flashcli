package venv

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/uv"
)

// Installer creates a venv and installs packages with uv (default) or pip
// (FLASHCLI_VENV_BACKEND=pip, an explicit escape hatch).
type Installer struct {
	UV     string // empty => pip
	Quiet  bool
	Runner Runner
}

// SelectInstaller resolves the venv installer backend.
//
// FLASHCLI_VENV_BACKEND: "uv" (default, required), "pip" (escape hatch), "auto"
// (uv if available, else pip).
func SelectInstaller(ctx context.Context, opt Options) (*Installer, error) {
	backend := strings.ToLower(strings.TrimSpace(os.Getenv("FLASHCLI_VENV_BACKEND")))
	if backend == "" {
		backend = "uv"
	}
	runner := opt.Runner
	if runner == nil {
		runner = ExecRunner{Stdio: !opt.Quiet}
	}
	switch backend {
	case "pip":
		return &Installer{Quiet: opt.Quiet, Runner: runner}, nil
	case "uv", "auto":
		bin, err := uv.Ensure(ctx, opt.Quiet, !opt.NoAutoInstall)
		if err != nil {
			if backend == "auto" {
				return &Installer{Quiet: opt.Quiet, Runner: runner}, nil
			}
			return nil, err
		}
		return &Installer{UV: bin, Quiet: opt.Quiet, Runner: runner}, nil
	default:
		return nil, fmt.Errorf("unknown FLASHCLI_VENV_BACKEND=%q (uv|pip|auto)", backend)
	}
}

// CreateVenv creates venvDir from basePython.
func (in *Installer) CreateVenv(ctx context.Context, basePython, venvDir string) error {
	if in.UV != "" {
		argv := []string{in.UV, "venv", "--python", basePython, "--seed", venvDir}
		return in.Runner.Run(ctx, argv, in.env())
	}
	return in.Runner.Run(ctx, []string{basePython, "-m", "venv", venvDir}, in.env())
}

// Install installs pip-style *args* (including any -q / --index-url) into the
// venv interpreter.
func (in *Installer) Install(ctx context.Context, python string, args []string) error {
	if in.UV != "" {
		argv := []string{in.UV, "pip", "install", "--python", python}
		argv = append(argv, args...)
		argv = append(argv, in.uvIndexArgs(args)...)
		return in.Runner.Run(ctx, argv, in.env())
	}
	argv := []string{python, "-m", "pip", "install"}
	return in.Runner.Run(ctx, append(argv, args...), in.env())
}

func (in *Installer) env() []string {
	env := os.Environ()
	if in.UV != "" {
		env = append(env, uv.Env()...)
	}
	return env
}

// uvIndexArgs lets PyPI satisfy dependencies of a command pinned to another
// index (the torch wheel index).
func (in *Installer) uvIndexArgs(args []string) []string {
	pypi := strings.TrimSpace(os.Getenv("PIP_INDEX_URL"))
	for i := 0; i+1 < len(args); i++ {
		if args[i] == "--index-url" && args[i+1] != pypi {
			out := []string{"--index-strategy", "unsafe-best-match"}
			if pypi != "" {
				out = append(out, "--extra-index-url", pypi)
			}
			return out
		}
	}
	return nil
}
