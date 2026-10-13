// Package doctor reports host capabilities relevant to running bundles.
package doctor

import (
	"os/exec"
	"strings"
)

// Check is one host capability probe result.
type Check struct {
	Name   string
	OK     bool
	Detail string
}

// Run probes the host for the tools flashcli needs.
func Run(goVersion string) []Check {
	return []Check{
		{Name: "flashcli-go", OK: true, Detail: goVersion},
		check("python3", "--version"),
		check("nvidia-smi", "-L"),
		check("nvcc", "--version"),
		check("readelf", "--version"),
	}
}

func check(name string, args ...string) Check {
	path, err := exec.LookPath(name)
	if err != nil {
		return Check{Name: name, OK: false, Detail: "not found"}
	}
	out, err := exec.Command(path, args...).CombinedOutput()
	detail := strings.SplitN(strings.TrimSpace(string(out)), "\n", 2)[0]
	if err != nil && detail == "" {
		return Check{Name: name, OK: false, Detail: "found (probe failed): " + err.Error()}
	}
	return Check{Name: name, OK: true, Detail: detail}
}
