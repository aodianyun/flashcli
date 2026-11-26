package setup

import (
	"bytes"
	"context"
	"debug/elf"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/mirror"
	"github.com/aodianyun/flashcli/go/internal/selfupdate"
	"github.com/aodianyun/flashcli/go/internal/version"
)

const (
	defaultReleaseBase = "https://github.com/aodianyun/flashcli/releases/download"
	defaultReleaseAPI  = "https://api.github.com/repos/aodianyun/flashcli/releases/latest"
	giteeReleaseBase   = "https://gitee.com/aodiansoft/flashcli/releases/download"
	giteeReleaseAPI    = "https://gitee.com/api/v5/repos/aodiansoft/flashcli/releases/latest"
	checksumsAsset     = "sha256sums.txt"
)

// ensureAssetBinaries prefers a verified local payload. If local files exist
// but are incomplete or invalid, it fails instead of masking the mismatch with
// a remote download. The returned cleanup func removes a temporary download
// directory.
func ensureAssetBinaries(ctx context.Context, env Env, opts *Options, out io.Writer) (func(), error) {
	return ensureAssetBinariesFrom(ctx, env, opts, out, executableDir())
}

func ensureAssetBinariesFrom(ctx context.Context, env Env, opts *Options, out io.Writer, exeDir string) (func(), error) {
	targetOS := "linux"
	arch := env.Arch
	names := []string{
		"flashcli-" + targetOS + "-" + arch,
		"flashserver-" + targetOS + "-" + arch,
	}
	dirs := assetCandidateDirs(opts.BinDir, exeDir)
	var localErrors []string
	for _, dir := range dirs {
		_, found, err := readLocalAssets(dir, names, arch, version.Version)
		if !found {
			continue
		}
		if err != nil {
			fmt.Fprintf(out, "local Linux payload rejected at %q: %v\n", dir, err)
			localErrors = append(localErrors, fmt.Sprintf("%s: %v", dir, err))
			continue
		}
		opts.BinDir = dir
		fmt.Fprintf(out, "using verified local Linux payload from %q\n", dir)
		return func() {}, nil
	}
	if len(localErrors) > 0 {
		return nil, fmt.Errorf("local Linux payload was found but no candidate passed validation: %s", strings.Join(localErrors, "; "))
	}

	fmt.Fprintf(out, "no local Linux payload found in %s; attempting the configured release download\n", strings.Join(dirs, ", "))
	tmp, err := os.MkdirTemp("", "flashserver-setup-assets-*")
	if err != nil {
		return nil, err
	}
	cleanup := func() { _ = os.RemoveAll(tmp) }
	if err := downloadAssets(ctx, opts, names, tmp, out); err != nil {
		cleanup()
		return nil, err
	}
	opts.BinDir = tmp
	return cleanup, nil
}

type localAsset struct {
	name string
	path string
}

func assetCandidateDirs(dirs ...string) []string {
	var out []string
	for _, dir := range dirs {
		if strings.TrimSpace(dir) == "" {
			continue
		}
		clean, err := filepath.Abs(filepath.Clean(dir))
		if err != nil {
			clean = filepath.Clean(dir)
		}
		duplicate := false
		for _, existing := range out {
			if runtime.GOOS == "windows" && strings.EqualFold(existing, clean) || existing == clean {
				duplicate = true
				break
			}
		}
		if !duplicate {
			out = append(out, clean)
		}
	}
	return out
}

func readLocalAssets(dir string, names []string, arch, expectedVersion string) ([]localAsset, bool, error) {
	assets := make([]localAsset, 0, len(names))
	missing := make([]string, 0, len(names))
	foundAny := false
	for _, name := range names {
		asset, found, err := locateLocalAsset(dir, name)
		if found {
			foundAny = true
		}
		if err != nil {
			return nil, true, err
		}
		if found {
			assets = append(assets, asset)
			continue
		}
		missing = append(missing, name)
	}
	if !foundAny {
		return nil, false, nil
	}
	if len(missing) > 0 {
		return nil, true, fmt.Errorf("incomplete payload; missing %s", strings.Join(missing, ", "))
	}

	sumsPath := filepath.Join(dir, checksumsAsset)
	sumsInfo, err := os.Lstat(sumsPath)
	if err != nil {
		return nil, true, fmt.Errorf("stat %s: %w", sumsPath, err)
	}
	if sumsInfo.Mode()&os.ModeSymlink != 0 || !sumsInfo.Mode().IsRegular() {
		return nil, true, fmt.Errorf("%s is not a regular file", sumsPath)
	}
	sumsBlob, err := os.ReadFile(sumsPath)
	if err != nil {
		return nil, true, fmt.Errorf("read %s: %w", sumsPath, err)
	}
	sums := selfupdate.ParseChecksums(string(sumsBlob))
	for _, asset := range assets {
		info, err := os.Lstat(asset.path)
		if err != nil {
			return nil, true, fmt.Errorf("stat %s: %w", asset.path, err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return nil, true, fmt.Errorf("%s is not a regular file", asset.path)
		}
		data, err := os.ReadFile(asset.path)
		if err != nil {
			return nil, true, fmt.Errorf("read %s: %w", asset.path, err)
		}
		want := sums[filepath.Base(asset.path)]
		if want == "" {
			want = sums[asset.name]
		}
		if err := selfupdate.Verify(data, want); err != nil {
			return nil, true, fmt.Errorf("verify %s: %w", asset.path, err)
		}
		if err := validateLinuxAsset(data, arch, expectedVersion); err != nil {
			return nil, true, fmt.Errorf("validate %s: %w", asset.path, err)
		}
	}
	return assets, true, nil
}

func locateLocalAsset(dir, name string) (localAsset, bool, error) {
	short := "flashcli"
	if strings.HasPrefix(name, "flashserver-") {
		short = "flashserver"
	}
	for _, candidate := range []string{name, short} {
		path := filepath.Join(dir, candidate)
		info, err := os.Lstat(path)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return localAsset{}, true, fmt.Errorf("stat %s: %w", path, err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return localAsset{}, true, fmt.Errorf("%s is not a regular file", path)
		}
		return localAsset{name: name, path: path}, true, nil
	}
	return localAsset{}, false, nil
}

func validateLinuxAsset(data []byte, arch, expectedVersion string) error {
	file, err := elf.NewFile(bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("not a valid Linux ELF executable: %w", err)
	}
	defer file.Close()
	if file.Class != elf.ELFCLASS64 || file.Data != elf.ELFDATA2LSB || file.Type != elf.ET_EXEC && file.Type != elf.ET_DYN {
		return fmt.Errorf("unexpected ELF format: class=%s data=%s type=%s", file.Class, file.Data, file.Type)
	}
	wantMachine := elf.EM_NONE
	switch arch {
	case "amd64":
		wantMachine = elf.EM_X86_64
	case "arm64":
		wantMachine = elf.EM_AARCH64
	default:
		return fmt.Errorf("unsupported Linux architecture %q", arch)
	}
	if file.Machine != wantMachine {
		return fmt.Errorf("ELF machine is %s, expected %s for %s", file.Machine, wantMachine, arch)
	}
	if expectedVersion != "" && expectedVersion != "dev" && !bytes.Contains(data, []byte(expectedVersion)) {
		return fmt.Errorf("version marker %q is missing", expectedVersion)
	}
	return nil
}

func downloadAssets(ctx context.Context, opts *Options, names []string, dir string, out io.Writer) error {
	mirror.Apply()
	base := strings.TrimSpace(opts.ReleaseBase)
	if base == "" {
		base = strings.TrimSpace(os.Getenv("FLASHCLI_GO_RELEASE_BASE"))
	}
	api := strings.TrimSpace(opts.ReleaseAPI)
	if api == "" {
		api = strings.TrimSpace(os.Getenv("FLASHCLI_GO_RELEASE_API"))
	}
	if base == "" || api == "" {
		if mirror.Enabled() {
			if base == "" {
				base = giteeReleaseBase
			}
			if api == "" {
				api = giteeReleaseAPI
			}
		} else {
			if base == "" {
				base = defaultReleaseBase
			}
			if api == "" {
				api = defaultReleaseAPI
			}
		}
	}
	ver := strings.TrimSpace(opts.ReleaseVersion)
	if ver == "" {
		if version.Version == "" || version.Version == "dev" {
			ver = "latest"
		} else {
			ver = version.Version
		}
	}
	if ver == "latest" {
		fmt.Fprintf(out, "resolve latest Linux payload version from %s\n", api)
		latest, err := selfupdate.LatestVersion(ctx, nil, api)
		if err != nil {
			return fmt.Errorf("resolve latest release: %w (use --bin-dir or --release-version)", err)
		}
		ver = latest
	}
	fmt.Fprintf(out, "remote Linux payload source: %s (version %s)\n", strings.TrimSuffix(base, "/"), ver)
	sumsURL := selfupdate.ReleaseURL(base, ver, checksumsAsset)
	if _, err := fmt.Fprintf(out, "download %s\n", sumsURL); err != nil {
		return err
	}
	sumsBlob, err := selfupdate.Download(ctx, nil, sumsURL)
	if err != nil {
		return fmt.Errorf("download %s: %w (use --bin-dir or --release-version)", sumsURL, err)
	}
	sums := selfupdate.ParseChecksums(string(sumsBlob))
	for _, baseName := range names {
		name := baseName
		url := selfupdate.ReleaseURL(base, ver, name)
		if _, err := fmt.Fprintf(out, "download %s\n", url); err != nil {
			return err
		}
		data, err := selfupdate.Download(ctx, nil, url)
		if err != nil {
			return fmt.Errorf("download %s: %w", url, err)
		}
		want := sums[name]
		if want == "" {
			return fmt.Errorf("%s not found in %s", name, sumsURL)
		}
		if err := selfupdate.Verify(data, want); err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
		if err := os.WriteFile(filepath.Join(dir, baseName), data, 0o755); err != nil {
			return err
		}
	}
	return nil
}
