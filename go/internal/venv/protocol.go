package venv

import (
	"context"
	"fmt"
	"os/exec"
	"strconv"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/mirror"
	"github.com/aodianyun/flashcli/go/internal/progress"
)

// RequiredCacheSchema is the on-disk cache layout the host reads/writes. It must
// match flashcli_bundle.version.CACHE_SCHEMA_VERSION.
//
// The bundle venv fingerprint only covers the manifest's python dependencies, so
// an existing venv can carry an older flashcli-bundle whose cache paths no
// longer match the host. EnsureProtocolCacheSchema upgrades just that package in
// place (no torch/dependency reinstall) when the schema is stale.
//
// v2: variant-independent keys <name>/<version> with per-variant weights under
// weights_dir (docs/bundle_publish_standard.md §4.4.1).
// v3: resolve the variant weights_dir from the raw block (scalar weights_dir).
// v4: script mode strips host-only flags (--checkpoint/--no-auto-install) from argv.
const RequiredCacheSchema = 4

// EnsureProtocolCacheSchema probes flashcli_bundle.CACHE_SCHEMA_VERSION in the
// venv and, when stale or unavailable, reinstalls only flashcli-bundle.
func EnsureProtocolCacheSchema(ctx context.Context, python string, opt Options) error {
	if python == "" {
		return nil
	}
	cur, ok := probeCacheSchema(ctx, python)
	if ok && cur >= RequiredCacheSchema {
		return nil
	}
	spec, origin, err := FlashcliBundleSpecOrigin()
	if err != nil {
		return err
	}
	if !opt.Quiet {
		progress.Note("venv: upgrading flashcli-bundle (cache schema %d -> %d) from %s", cur, RequiredCacheSchema, origin)
	}
	inst, err := SelectInstaller(ctx, opt)
	if err != nil {
		return err
	}
	args := []string{"--upgrade", "--force-reinstall", "--no-deps", "--no-cache-dir"}
	args = append(args, mirror.PipExtraArgs()...)
	args = append(args, spec)
	if err := inst.Install(ctx, python, args); err != nil {
		return fmt.Errorf("upgrade flashcli-bundle: %w", err)
	}
	return nil
}

// probeCacheSchema runs the venv interpreter and returns
// (CACHE_SCHEMA_VERSION, true) on success.
func probeCacheSchema(ctx context.Context, python string) (int, bool) {
	const code = "import flashcli_bundle.version as v; print(getattr(v, 'CACHE_SCHEMA_VERSION', 0))"
	cmd := exec.CommandContext(ctx, python, "-c", code)
	var out strings.Builder
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		return 0, false
	}
	n, err := strconv.Atoi(strings.TrimSpace(out.String()))
	if err != nil {
		return 0, false
	}
	return n, true
}
