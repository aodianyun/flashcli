"""Resolve model bundle path from preset catalog, git cache, and CLI overrides."""

from __future__ import annotations

from pathlib import Path

from flashcli import config
from flashcli.bundle.git import ensure_bundle_from_git, resolve_cached_bundle_root
from flashcli.bundle.zip import (
    ensure_bundle_from_zip,
    resolve_cached_zip_bundle_root,
    zip_spec,
)
import json

from flashcli.bundle.manifest import BundleManifest, load_bundle_manifest
from flashcli.bundle.ref import is_bundle_root
from flashcli.models.registry import Preset


def _flashcli_root() -> Path:
    """Directory containing ``models/models.yaml`` (the flashcli package root)."""
    return config.MODELS_YAML.resolve().parent.parent


def _resolve_catalog_bundle_path(path_str: str) -> Path:
    """Resolve ``bundle.path``; relative paths are under the flashcli package root."""
    raw = Path(path_str).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return (_flashcli_root() / raw).resolve()


def _bundle_cfg(preset: Preset) -> dict:
    raw = preset.raw.get("bundle") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _local_bundle_ready(root: Path) -> bool:
    """True when a catalog ``bundle.path`` tree is usable without a build step."""
    bundle_json = root / "flashcli-bundle.json"
    if not bundle_json.is_file():
        return False
    try:
        data = json.loads(bundle_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("native_runtime") is False:
        return (
            (root / "runtime" / "manifest.json").is_file()
            and (root / "runtime" / "python" / "partner").is_dir()
            and is_bundle_root(root)
        )
    lib_kernels = root / "runtime" / "lib" / "flash_rt_kernels.so"
    legacy_py = root / "runtime" / "python" / "flash_rt"
    partner_pi05 = root / "runtime" / "python" / "partner" / "models" / "pi05"
    if lib_kernels.is_file() and legacy_py.is_dir():
        return True
    if lib_kernels.is_file() and partner_pi05.is_dir():
        return True
    return False


def resolve_bundle_root(
    preset: Preset,
    *,
    bundle_override: Path | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
    checkpoint: Path | None = None,
    fetch_git: bool = True,
    quiet: bool = False,
) -> Path:
    """Return absolute bundle root directory."""
    if bundle_override is not None:
        root = bundle_override.expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Bundle directory not found: {root}")
        return root

    cfg = _bundle_cfg(preset)
    if cfg.get("path"):
        root = _resolve_catalog_bundle_path(str(cfg["path"]))
        if not root.is_dir():
            raise FileNotFoundError(f"Bundle path not found: {root}")
        if _local_bundle_ready(root):
            return root
        build_hint = root / "build.sh"
        hint = (
            f" Run: bash {build_hint}"
            if build_hint.is_file()
            else " Run: bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir <path>"
        )
        raise FileNotFoundError(
            f"Bundle at {root} is not assembled yet "
            f"(need runtime/lib/flash_rt_kernels.so + runtime/python/flash_rt, "
            f"or native_runtime:false with runtime/manifest.json).{hint}"
        )

    if zip_spec(preset) is not None:
        cached_zip = resolve_cached_zip_bundle_root(preset)
        if cached_zip is not None:
            return cached_zip
        if fetch_git:
            return ensure_bundle_from_zip(preset, quiet=quiet)
        raise FileNotFoundError(
            f"No cached zip bundle for preset {preset.name!r}. "
            f"Run 'flashcli bundle sync {preset.name}' or pass --bundle."
        )

    cached = resolve_cached_bundle_root(
        preset, bundle_ref=bundle_ref or bundle_version
    )
    if cached is not None:
        return cached

    if fetch_git and cfg.get("git"):
        return ensure_bundle_from_git(
            preset,
            bundle_ref=bundle_ref or bundle_version,
            quiet=quiet,
        )

    if checkpoint is not None:
        ckpt = checkpoint.resolve()
        for name in ("flashcli-bundle", "bundle"):
            nested = ckpt.parent / name
            if nested.is_dir() and (nested / "flashcli-bundle.json").is_file():
                return nested.resolve()
            nested2 = ckpt / name
            if nested2.is_dir() and (nested2 / "flashcli-bundle.json").is_file():
                return nested2.resolve()

    raise FileNotFoundError(
        f"No model bundle for preset {preset.name!r}. "
        f"Configure bundle.path, bundle.zip, or bundle.git in models.yaml "
        f"(then run 'flashcli bundle sync {preset.name}') or pass --bundle."
    )


def load_preset_bundle(
    preset: Preset,
    *,
    bundle_override: Path | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
    checkpoint: Path | None = None,
    fetch_git: bool = True,
    quiet: bool = False,
) -> BundleManifest:
    root = resolve_bundle_root(
        preset,
        bundle_override=bundle_override,
        bundle_ref=bundle_ref or bundle_version,
        checkpoint=checkpoint,
        fetch_git=fetch_git,
        quiet=quiet,
    )
    return load_bundle_manifest(root)


