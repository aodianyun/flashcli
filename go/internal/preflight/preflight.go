// Package preflight detects the host runtime environment key
// (sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}) and matches it against a bundle's
// runtime map. Mirrors flashcli_bundle/runtime_env.py + detect.py.
package preflight

import (
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"strconv"
	"strings"
)

// GpuInfo is the detected host GPU/runtime.
type GpuInfo struct {
	SM         string
	CudaTag    string
	OSName     string
	Arch       string
	TorchIndex string
	Driver     string
	GPUName    string
}

// EnvKey is a parsed runtime environment key.
type EnvKey struct {
	PlatformTail string
	OSName       string
	Arch         string
	PythonMinor  string
	SM           string
	CudaTag      string
}

// Name renders the catalog key.
func (e EnvKey) Name() string {
	base := e.PlatformTail + "-" + e.OSName + "-" + e.Arch
	if e.PythonMinor != "" {
		return base + "-py" + e.PythonMinor
	}
	return base
}

var pySuffixRe = regexp.MustCompile(`^py(3\d{2})$`)

// ParseEnvKey parses an env key with tail ...-{os}-{arch}[-py{NNN}].
func ParseEnvKey(name string) (EnvKey, error) {
	parts := []string{}
	for _, p := range strings.Split(strings.TrimSpace(name), "-") {
		if p != "" {
			parts = append(parts, p)
		}
	}
	pythonMinor := ""
	if len(parts) > 0 {
		if m := pySuffixRe.FindStringSubmatch(parts[len(parts)-1]); m != nil {
			pythonMinor = m[1]
			parts = parts[:len(parts)-1]
		}
	}
	if len(parts) < 3 {
		return EnvKey{}, fmt.Errorf("invalid catalog environment key: %q", name)
	}
	arch := parts[len(parts)-1]
	osName := parts[len(parts)-2]
	platformTail := strings.Join(parts[:len(parts)-2], "-")
	if platformTail == "" {
		return EnvKey{}, fmt.Errorf("invalid catalog environment key: %q", name)
	}
	sm, cuda := parseNvidiaSegments(platformTail)
	return EnvKey{PlatformTail: platformTail, OSName: osName, Arch: arch, PythonMinor: pythonMinor, SM: sm, CudaTag: cuda}, nil
}

func parseNvidiaSegments(tail string) (string, string) {
	var sm, cuda string
	for _, part := range strings.Split(tail, "-") {
		if sm == "" && strings.HasPrefix(part, "sm") && len(part) > 2 {
			sm = part[2:]
		} else if cuda == "" && strings.HasPrefix(part, "cu") && len(part) > 2 {
			cuda = part[2:]
		}
	}
	return sm, cuda
}

// DetectGPU probes nvidia-smi; returns nil when unavailable.
func DetectGPU() *GpuInfo {
	path, err := exec.LookPath("nvidia-smi")
	if err != nil {
		return nil
	}
	out, err := exec.Command(path, "--query-gpu=name,compute_cap,driver_version", "--format=csv,noheader").Output()
	if err != nil {
		return nil
	}
	line := strings.TrimSpace(strings.SplitN(string(out), "\n", 2)[0])
	if line == "" {
		return nil
	}
	parts := strings.Split(line, ",")
	if len(parts) < 2 {
		return nil
	}
	name := strings.TrimSpace(parts[0])
	sm := parseSM(strings.TrimSpace(parts[1]))
	driver := ""
	if len(parts) > 2 {
		driver = strings.TrimSpace(parts[2])
	}
	cuda := cudaTagFromEnv()
	if cuda == "" {
		cuda = detectCudaTagFromNvcc()
	}
	if cuda == "" {
		cuda = detectCudaTagFromNvidiaSmi()
	}
	if cuda == "" {
		if sm == "120" || sm == "110" {
			cuda = "128"
		} else {
			cuda = "124"
		}
	}
	return &GpuInfo{
		SM:         sm,
		CudaTag:    cuda,
		OSName:     strings.ToLower(runtime.GOOS),
		Arch:       normalizeArch(runtime.GOARCH),
		TorchIndex: TorchIndexForTag(cuda),
		Driver:     driver,
		GPUName:    name,
	}
}

// VariantDirName builds the host env key for this machine.
func VariantDirName(gpu *GpuInfo, pythonABI string) string {
	return EnvKey{
		PlatformTail: "sm" + gpu.SM + "-cu" + gpu.CudaTag,
		OSName:       gpu.OSName,
		Arch:         gpu.Arch,
		PythonMinor:  pythonABI,
		SM:           gpu.SM,
		CudaTag:      gpu.CudaTag,
	}.Name()
}

// ResolveRuntimeEnvKey picks the best manifest runtime key (exact then fuzzy).
func ResolveRuntimeEnvKey(runtimeMap map[string]string, hostKey string) string {
	if override := strings.TrimSpace(os.Getenv("FLASHCLI_RUNTIME_ENV_KEY")); override != "" {
		if _, ok := runtimeMap[override]; ok {
			return override
		}
	}
	if _, ok := runtimeMap[hostKey]; ok {
		return hostKey
	}
	host, err := ParseEnvKey(hostKey)
	if err != nil {
		return ""
	}
	bestKey := ""
	bestScore := 0
	for key := range runtimeMap {
		artifact, err := ParseEnvKey(key)
		if err != nil {
			continue
		}
		if score := ScoreEnvKeyMatch(artifact, host); score > bestScore {
			bestScore = score
			bestKey = key
		}
	}
	if bestScore > 0 {
		return bestKey
	}
	return ""
}

// ScoreEnvKeyMatch ranks an artifact key against the host key (higher = better).
func ScoreEnvKeyMatch(artifact, host EnvKey) int {
	if artifact.PythonMinor != host.PythonMinor ||
		artifact.OSName != host.OSName || artifact.Arch != host.Arch {
		return 0
	}
	score := 20
	if artifact.PlatformTail == host.PlatformTail {
		return score + 15
	}
	if artifact.SM != "" && host.SM != "" {
		if artifact.SM == host.SM {
			score += 10
		} else {
			score += 6
		}
	}
	if artifact.CudaTag != "" && host.CudaTag != "" {
		if artifact.CudaTag == host.CudaTag {
			score += 5
		} else if cudaFamily(artifact.CudaTag) == cudaFamily(host.CudaTag) {
			score += 3
		}
	}
	return score
}

// TorchIndexForTag maps a CUDA tag to a PyTorch wheel index name.
func TorchIndexForTag(tag string) string {
	if tag == "128" || tag == "130" {
		return "cu128"
	}
	return "cu124"
}

func cudaFamily(tag string) string {
	tag = strings.TrimSpace(tag)
	if strings.HasPrefix(tag, "13") || tag == "130" {
		return "13"
	}
	if strings.HasPrefix(tag, "12") || tag == "124" || tag == "128" || tag == "120" {
		return "12"
	}
	if len(tag) >= 2 {
		return tag[:2]
	}
	return tag
}

func cudaTagFromEnv() string {
	raw := strings.ToLower(strings.TrimSpace(os.Getenv("FLASHCLI_CUDA_TAG")))
	raw = strings.TrimLeft(raw, "cu")
	return raw
}

var nvccReleaseRe = regexp.MustCompile(`release\s+([0-9]+)\.([0-9]+)`)
var smiCudaRe = regexp.MustCompile(`CUDA Version:\s*([0-9]+)\.([0-9]+)`)

func detectCudaTagFromNvcc() string {
	path, err := exec.LookPath("nvcc")
	if err != nil {
		return ""
	}
	out, err := exec.Command(path, "--version").Output()
	if err != nil {
		return ""
	}
	m := nvccReleaseRe.FindStringSubmatch(string(out))
	if m == nil {
		return ""
	}
	return cudaTagFromVersion(m[1], m[2])
}

func detectCudaTagFromNvidiaSmi() string {
	path, err := exec.LookPath("nvidia-smi")
	if err != nil {
		return ""
	}
	out, err := exec.Command(path).Output()
	if err != nil {
		return ""
	}
	m := smiCudaRe.FindStringSubmatch(string(out))
	if m == nil {
		return ""
	}
	return cudaTagFromVersion(m[1], m[2])
}

func cudaTagFromVersion(major, minor string) string {
	maj, _ := strconv.Atoi(major)
	min, _ := strconv.Atoi(minor)
	switch {
	case maj >= 13:
		return "130"
	case maj == 12 && min >= 8:
		return "128"
	case maj == 12 && min >= 4:
		return "124"
	case maj == 12:
		return "120"
	}
	return ""
}

func parseSM(computeCap string) string {
	parts := strings.Split(strings.TrimSpace(computeCap), ".")
	if len(parts) == 2 {
		a, _ := strconv.Atoi(parts[0])
		b, _ := strconv.Atoi(parts[1])
		return strconv.Itoa(a) + strconv.Itoa(b)
	}
	return strings.ReplaceAll(computeCap, ".", "")
}

func normalizeArch(goarch string) string {
	switch goarch {
	case "amd64":
		return "x86_64"
	case "arm64":
		return "aarch64"
	}
	return goarch
}
