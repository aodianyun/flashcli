"""Resolve model weights declared in a model bundle (protocol; resolve only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flashcli_bundle import paths as config
from flashcli_bundle.bundle_config import bundle_dict, bundle_list
from flashcli_bundle.checkpoint import (
    has_checkpoint_weight_files,
    has_usable_checkpoint,
    weights_require_norm_stats,
)
from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.preset import Preset
from flashcli_bundle.preset_ref import preset_cache_key
from flashcli_bundle.variants import (
    has_bundle_variants,
    resolve_bundle_variant,
    variant_extra_weights,
    variant_weights_dir,
    variant_weights_spec,
)

_SKIP_WEIGHT_NAMES = frozenset({".flashcli_model.json", ".gitkeep"})

_HOST_PULL_MSG = (
    "Weight download is only supported on the host flashcli CLI. "
    "Run: flashcli pull {ref}"
)


def bundle_weights_dir(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> Path:
    if has_bundle_variants(bundle):
        key = resolve_bundle_variant(bundle, variant)
        rel = variant_weights_dir(bundle, key)
    else:
        rel = str(bundle.raw.get("weights_dir", "checkpoint")).strip() or "checkpoint"
    return (bundle.bundle_root / rel).resolve()


def has_local_weights(
    path: Path,
    *,
    weights_spec: dict[str, Any] | None = None,
) -> bool:
    if not path.is_dir():
        return False
    require_ns = weights_require_norm_stats(weights_spec)
    if has_usable_checkpoint(path, require_norm_stats=require_ns):
        return True
    if require_ns and has_checkpoint_weight_files(path):
        return False
    for entry in path.iterdir():
        if entry.name in _SKIP_WEIGHT_NAMES or entry.name.startswith("."):
            continue
        if entry.name == ".cache":
            continue
        if entry.is_dir() and has_usable_checkpoint(
            entry, require_norm_stats=require_ns
        ):
            return True
    return False


def weights_spec(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> dict[str, Any]:
    if has_bundle_variants(bundle):
        key = resolve_bundle_variant(bundle, variant)
        return variant_weights_spec(bundle, key)
    return bundle_dict(bundle, "weights")


def extra_weights_spec(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> dict[str, Any]:
    if has_bundle_variants(bundle):
        key = resolve_bundle_variant(bundle, variant)
        return variant_extra_weights(bundle, key)
    extra = bundle_dict(bundle, "extra_weights")
    if extra:
        return extra
    return {}


def post_pull_steps(bundle: BundleManifest) -> list[Any]:
    return bundle_list(bundle, "post_pull")


def apply_bundle_env(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> None:
    """Write manifest ``env`` into the process (engine entry only; see ``entry_env``)."""
    import os

    if has_bundle_variants(bundle):
        from flashcli_bundle.variants import variant_env

        key = resolve_bundle_variant(bundle, variant)
        merged = variant_env(bundle, key)
    else:
        merged = bundle_dict(bundle, "env")
    for key, value in merged.items():
        if isinstance(value, str):
            os.environ[key] = value.format(
                models_dir=str(config.MODELS_DIR),
                bundle_root=str(bundle.bundle_root.resolve()),
            )


def _weights_missing_error(preset: Preset) -> FileNotFoundError:
    return FileNotFoundError(
        f"Model weights for preset {preset.name!r} are not available "
        "(no bundle-local checkpoint and nothing in the flashcli cache).\n"
        f"Run on the host CLI: flashcli pull {preset.name}"
    )


def _extra_weights_missing_error(key: str, dest: Path) -> FileNotFoundError:
    return FileNotFoundError(
        f"Extra weights {key!r} are not cached at {dest}.\n"
        "Run on the host CLI: flashcli pull <preset>"
    )


def _extra_dest(
    bundle: BundleManifest | None,
    key: str,
    spec: dict[str, Any],
) -> Path:
    if bundle is not None:
        rel = str(spec.get("relative_dir", "")).strip()
        if rel:
            return (bundle.bundle_root / rel).resolve()
    cache_name = str(spec.get("cache_name", key))
    return config.MODELS_DIR / cache_name


def extra_weight_dir(
    bundle: BundleManifest,
    key: str,
    spec: dict[str, Any],
) -> Path:
    """Resolved on-disk directory for one ``extra_weights`` entry."""
    return _extra_dest(bundle, key, spec)


def require_extra_weights_cached(
    bundle: BundleManifest | None,
    *,
    variant: str | None = None,
) -> None:
    """Raise if manifest extra_weights are not present (no download)."""
    if bundle is None:
        return
    extra = extra_weights_spec(bundle, variant=variant)
    for key, spec in extra.items():
        if not isinstance(spec, dict):
            continue
        repo = str(spec.get("repo", "")).strip()
        if not repo:
            continue
        dest = _extra_dest(bundle, key, spec)
        patterns = spec.get("allow_patterns")
        if isinstance(patterns, list):
            patterns = [str(p) for p in patterns]
        else:
            patterns = None
        from flashcli_bundle.checkpoint import has_cached_weight_files

        require_ns = weights_require_norm_stats(spec)
        if has_cached_weight_files(dest, patterns, require_norm_stats=require_ns):
            continue
        raise _extra_weights_missing_error(key, dest)


def resolve_checkpoint(
    preset: Preset,
    bundle: BundleManifest | None = None,
    *,
    checkpoint_override: Path | None = None,
    variant: str | None = None,
) -> Path | None:
    if checkpoint_override is not None:
        path = checkpoint_override.expanduser().resolve()
        return path if path.exists() else None
    spec = weights_spec(bundle, variant=variant) if bundle is not None else {}
    if bundle is not None:
        local = bundle_weights_dir(bundle, variant=variant)
        if has_local_weights(local, weights_spec=spec):
            return local
    cache = config.MODELS_DIR / preset_cache_key(preset)
    marker = cache / ".flashcli_model.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            ckpt = Path(str(data.get("checkpoint", ""))).expanduser()
            if ckpt.is_dir() and has_local_weights(ckpt, weights_spec=spec):
                return ckpt.resolve()
        except json.JSONDecodeError:
            pass
    nested = cache / "checkpoint"
    if has_local_weights(nested, weights_spec=spec):
        return nested.resolve()
    return None


def ensure_checkpoint(
    preset: Preset,
    bundle: BundleManifest | None = None,
    *,
    checkpoint_override: Path | None = None,
    variant: str | None = None,
    quiet: bool = False,
    download: bool = True,
) -> Path:
    """Resolve checkpoint without downloading (raises if missing and *download* is False)."""
    if checkpoint_override is not None:
        path = checkpoint_override.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        return path

    if bundle is None:
        raise ValueError(
            f"No bundle for preset {preset.name!r}; weights must come from "
            "flashcli-bundle.json via a resolved model bundle."
        )

    spec = weights_spec(bundle, variant=variant)
    local = bundle_weights_dir(bundle, variant=variant)
    if has_local_weights(local, weights_spec=spec):
        if not quiet:
            print(f"Using bundle-local weights: {local}")
        require_extra_weights_cached(bundle, variant=variant)
        return local

    existing = resolve_checkpoint(preset, bundle=bundle, variant=variant)
    if existing is not None:
        if not quiet:
            print(f"Using cached weights: {existing}")
        require_extra_weights_cached(bundle, variant=variant)
        return existing

    if not download:
        raise _weights_missing_error(preset)
    raise RuntimeError(_HOST_PULL_MSG.format(ref=preset.name))
