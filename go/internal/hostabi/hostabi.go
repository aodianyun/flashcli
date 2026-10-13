// Package hostabi checks the host glibc/libstdc++ can satisfy the versioned
// symbols required by a bundle's native .so files. Mirrors
// flashcli_bundle/native_host_abi.py (reads ELF version needs; feeds failures).
package hostabi

import (
	"os"
	"os/exec"
	"regexp"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/errs"
)

var (
	glibcRe   = regexp.MustCompile(`\bGLIBC_([0-9]+(?:\.[0-9]+)*)\b`)
	glibcxxRe = regexp.MustCompile(`\bGLIBCXX_([0-9]+(?:\.[0-9]+)*)\b`)
	cxxabiRe  = regexp.MustCompile(`\bCXXABI_([0-9]+(?:\.[0-9]+)*)\b`)
)

// Requirements is the max versioned symbol requirement per library family.
type Requirements struct {
	Glibc   string
	Glibcxx string
	Cxxabi  string
	Dirs    []string
}

func maxVersion(a, b string) string {
	if a == "" {
		return b
	}
	if b == "" {
		return a
	}
	if VersionAtLeast(a, b) {
		return a
	}
	return b
}

// VersionAtLeast reports whether have >= need (numeric component compare).
func VersionAtLeast(have, need string) bool {
	return cmpVersion(have, need) >= 0
}

func cmpVersion(a, b string) int {
	as := strings.Split(a, ".")
	bs := strings.Split(b, ".")
	for i := 0; i < len(as) || i < len(bs); i++ {
		var ai, bi int
		if i < len(as) {
			ai = atoi(as[i])
		}
		if i < len(bs) {
			bi = atoi(bs[i])
		}
		if ai != bi {
			if ai < bi {
				return -1
			}
			return 1
		}
	}
	return 0
}

func atoi(s string) int {
	n := 0
	for _, r := range s {
		if r < '0' || r > '9' {
			break
		}
		n = n*10 + int(r-'0')
	}
	return n
}

// ParseVersionText extracts max needs from readelf -V / objdump -p output.
func ParseVersionText(text string) Requirements {
	maxOf := func(re *regexp.Regexp) string {
		best := ""
		for _, m := range re.FindAllStringSubmatch(text, -1) {
			best = maxVersion(best, m[1])
		}
		return best
	}
	return Requirements{Glibc: maxOf(glibcRe), Glibcxx: maxOf(glibcxxRe), Cxxabi: maxOf(cxxabiRe)}
}

func elfVersionText(so string) string {
	if p, err := exec.LookPath("readelf"); err == nil {
		if out, err := exec.Command(p, "-V", so).Output(); err == nil && strings.Contains(string(out), "Version") {
			return string(out)
		}
	}
	if p, err := exec.LookPath("objdump"); err == nil {
		if out, err := exec.Command(p, "-p", so).Output(); err == nil {
			return string(out)
		}
	}
	return ""
}

// RequirementsFor merges requirements across the given .so paths.
func RequirementsFor(sos []string) Requirements {
	var merged Requirements
	for _, so := range sos {
		req := ParseVersionText(elfVersionText(so))
		merged.Glibc = maxVersion(merged.Glibc, req.Glibc)
		merged.Glibcxx = maxVersion(merged.Glibcxx, req.Glibcxx)
		merged.Cxxabi = maxVersion(merged.Cxxabi, req.Cxxabi)
		merged.Dirs = append(merged.Dirs, so)
	}
	return merged
}

// HostProvides returns the host's max glibc/GLIBCXX/CXXABI versions.
func HostProvides() Requirements {
	return Requirements{
		Glibc:   maxFromLib("libc.so.6", "GLIBC"),
		Glibcxx: maxFromLib("libstdc++.so.6", "GLIBCXX"),
		Cxxabi:  maxFromLib("libstdc++.so.6", "CXXABI"),
	}
}

func findLib(name string) string {
	if p, err := exec.LookPath("ldconfig"); err == nil {
		if out, err := exec.Command(p, "-p").Output(); err == nil {
			for _, line := range strings.Split(string(out), "\n") {
				if !strings.Contains(line, name) || !strings.Contains(line, "=>") {
					continue
				}
				path := strings.TrimSpace(strings.SplitN(line, "=>", 2)[1])
				if info, err := os.Stat(path); err == nil && !info.IsDir() {
					return path
				}
			}
		}
	}
	for _, c := range []string{"/lib/x86_64-linux-gnu/" + name, "/usr/lib/x86_64-linux-gnu/" + name, "/lib64/" + name, "/usr/lib64/" + name} {
		if _, err := os.Stat(c); err == nil {
			return c
		}
	}
	return ""
}

func maxFromLib(libName, prefix string) string {
	path := findLib(libName)
	if path == "" {
		return ""
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	limit := len(data)
	if limit > 4*1024*1024 {
		limit = 4 * 1024 * 1024
	}
	re := regexp.MustCompile(`\b` + regexp.QuoteMeta(prefix) + `_([0-9]+(?:\.[0-9]+)*)\b`)
	best := ""
	for _, m := range re.FindAllStringSubmatch(string(data[:limit]), -1) {
		best = maxVersion(best, m[1])
	}
	return best
}

// Check returns mismatch descriptions (empty = OK). Skips when disabled.
func Check(sos []string, quiet bool) []string {
	if len(sos) == 0 {
		return nil
	}
	switch strings.ToLower(strings.TrimSpace(os.Getenv("FLASHCLI_SKIP_NATIVE_HOST_ABI"))) {
	case "1", "true", "yes", "on":
		return nil
	}
	needs := RequirementsFor(sos)
	host := HostProvides()
	var errors []string
	if needs.Glibc != "" && !VersionAtLeast(host.Glibc, needs.Glibc) {
		errors = append(errors, "host glibc too old: need GLIBC_"+needs.Glibc+", host provides GLIBC_"+orUnknown(host.Glibc))
	}
	if needs.Glibcxx != "" && !VersionAtLeast(host.Glibcxx, needs.Glibcxx) {
		errors = append(errors, "host libstdc++ too old: need GLIBCXX_"+needs.Glibcxx+", host provides GLIBCXX_"+orUnknown(host.Glibcxx))
	}
	if needs.Cxxabi != "" && !VersionAtLeast(host.Cxxabi, needs.Cxxabi) {
		errors = append(errors, "host libstdc++ CXXABI too old: need CXXABI_"+needs.Cxxabi+", host provides CXXABI_"+orUnknown(host.Cxxabi))
	}
	return errors
}

// Ensure wraps Check, returning an Environment error on mismatch.
func Ensure(sos []string, quiet bool) error {
	if mismatches := Check(sos, quiet); len(mismatches) > 0 {
		return errs.EnvWrapf("Host system libraries are too old for this bundle's native runtime: %s (skip: FLASHCLI_SKIP_NATIVE_HOST_ABI=1)", strings.Join(mismatches, "; "))
	}
	return nil
}

func orUnknown(v string) string {
	if v == "" {
		return "unknown"
	}
	return v
}
