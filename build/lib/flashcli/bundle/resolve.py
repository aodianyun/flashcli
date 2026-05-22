"""Resolve model bundle path from preset catalog, git cache, and CLI overrides."""

from __future__ import annotations

import json
from pathlib import Path

from flashcli import config
from flashcli.bundle.catalog import (
    BundleCatalogError,
    BundleVariantNotFoundError,
    effective_bundle_cfg_for_preset,
)
from flashcli.bundle.git import (
    ensure_bundle_from_git,
    find_bundle_root_in_clone,
    resolve_cached_bundle_root,
)
from flashcli.runtime.detect import detect_gpu_or_raise
from flashcli.bundle.manifest import (
    bundle_format_version,
    bundle_modules,
    load_bundle_manifest,
    module_file_path,
)
from flashcli.bundle.zip import (
    ensure_bundle_from_zip,
    resolve_cached_zip_bundle_root,
    zip_spec,
)

from flashcli.bundle.manifest import BundleManifest
from flashcli.bundle.ref import is_bundle_root
from flashcli.models.registry import Preset


def _flashcli_root() -> Path:
    """Repo root for ``bundle.path`` (editable); package dir when only wheel catalog."""
    return config.package_root()


def _resolve_catalog_bundle_path(path_str: str) -> Path:
    """Resolve ``bundle.path``; relative paths are under the flashcli package root."""
    raw = Path(path_str).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return (_flashcli_root() / raw).resolve()


def _entry_files_present(root: Path, data: dict) -> bool:
    entry = data.get("entry") or {}
    if not isinstance(entry, dict):
        return False
    try:
        bundle = load_bundle_manifest(root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return False
    from flashcli.bundle.manifest import validate_bundle_layout

    errs = validate_bundle_layout(bundle)
    entry_errs = [e for e in errs if e.startswith("entry.")]
    return not entry_errs


def _legacy_bundle_ready(root: Path, data: dict) -> bool:
    lib_kernels = root / "runtime" / "lib" / "flash_rt_kernels.so"
    legacy_py = root / "runtime" / "python" / "flash_rt"
    partner_pi05 = root / "runtime" / "python" / "partner" / "models" / "pi05"
    if lib_kernels.is_file() and legacy_py.is_dir():
        return True
    if lib_kernels.is_file() and partner_pi05.is_dir():
        return True
    if (root / "runtime" / "manifest.json").is_file() and (
        root / "runtime" / "python" / "partner"
    ).is_dir():
        return True
    return False


def _v2_bundle_ready(root: Path, data: dict) -> bool:
    if not isinstance(data.get("python_dependencies"), dict):
        return False
    try:
        bundle = load_bundle_manifest(root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return False
    for mod in bundle_modules(bundle):
        if mod.get("optional"):
            continue
        file_rel = str(mod.get("file", "")).strip()
        if file_rel and not module_file_path(bundle, file_rel).is_file():
            return False
    return _entry_files_present(root, data)


def _local_bundle_ready(root: Path) -> bool:
    """True when a catalog ``bundle.path`` tree is usable without a build step."""
    bundle_json = root / "flashcli-bundle.json"
    if not bundle_json.is_file():
        return False
    try:
        data = json.loads(bundle_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not is_bundle_root(root):
        return False
    if bundle_format_version(
        load_bundle_manifest(root)
    ) >= 2:
        return _v2_bundle_ready(root, data)
    return _legacy_bundle_ready(root, data) or _v2_bundle_ready(root, data)


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

    try:
        cfg = effective_bundle_cfg_for_preset(preset)
    except (BundleCatalogError, BundleVariantNotFoundError):
        raise

    if cfg.get("path"):
        root = _resolve_catalog_bundle_path(str(cfg["path"]))
        if not root.is_dir():
            raise FileNotFoundError(f"Bundle path not found: {root}")
        if _local_bundle_ready(root):
            return root
        variants_subdir = str(cfg.get("variants_dir", "variants")).strip() or "variants"
        if (root / variants_subdir).is_dir():
            gpu = detect_gpu_or_raise()
            return find_bundle_root_in_clone(
                root, preset, gpu, bundle_cfg=cfg
            )
        build_hint = root / "build.sh"
        hint = (
            f" Run: bash {build_hint}"
            if build_hint.is_file()
            else " Run: bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir <path>"
        )
        raise FileNotFoundError(
            f"Bundle at {root} is not assembled yet "
            f"(need flashcli-bundle.json with entry + python_dependencies, "
            f"and built modules per modules[]).{hint}"
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

    raise FileNotFoundError(
        f"No bundle source for preset {preset.name!r}. "
        f"Configure bundle.path, bundle.zip, or bundle.git in models.yaml "
        f"or pass --bundle."
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
        bundle_ref=bundle_ref,
        bundle_version=bundle_version,
        checkpoint=checkpoint,
        fetch_git=fetch_git,
        quiet=quiet,
    )
    return load_bundle_manifest(root)
