package setup

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
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

// ensureAssetBinaries uses local release assets when present, otherwise
// downloads flashcli/flashserver from the release matching this setup build.
// The returned cleanup func removes a temporary download directory.
func ensureAssetBinaries(ctx context.Context, env Env, opts *Options, out io.Writer) (func(), error) {
	targetOS := "linux"
	arch := env.Arch
	names := []string{
		"flashcli-" + targetOS + "-" + arch,
		"flashserver-" + targetOS + "-" + arch,
	}
	if assetsPresent(opts.BinDir, names) {
		return func() {}, nil
	}

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

func assetsPresent(dir string, names []string) bool {
	for _, name := range names {
		short := "flashcli"
		if strings.HasPrefix(name, "flashserver-") {
			short = "flashserver"
		}
		if fileExists(filepath.Join(dir, name)) || fileExists(filepath.Join(dir, short)) {
			continue
		}
		return false
	}
	return true
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
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
		latest, err := selfupdate.LatestVersion(ctx, nil, api)
		if err != nil {
			return fmt.Errorf("resolve latest release: %w (use --bin-dir or --release-version)", err)
		}
		ver = latest
	}
	sumsURL := selfupdate.ReleaseURL(base, ver, checksumsAsset)
	sumsBlob, err := selfupdate.Download(ctx, nil, sumsURL)
	if err != nil {
		return fmt.Errorf("download %s: %w (use --bin-dir or --release-version)", sumsURL, err)
	}
	sums := selfupdate.ParseChecksums(string(sumsBlob))
	for _, baseName := range names {
		name := versionedAssetName(baseName, ver)
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

// versionedAssetName appends the release version before the extension:
// flashcli-linux-amd64-v1.0.7.20261111.
func versionedAssetName(name, ver string) string {
	ver = strings.TrimPrefix(strings.TrimSpace(ver), "v")
	ext := filepath.Ext(name)
	return strings.TrimSuffix(name, ext) + "-v" + ver + ext
}
