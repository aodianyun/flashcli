"""Resolve bundle sources from models.yaml (single zip/path/git per preset)."""

from __future__ import annotations

from typing import Any

from flashcli.bundle.runtime_env import host_python_minor, variant_dir_name
from flashcli.models.registry import Preset
from flashcli.runtime.detect import GpuInfo, detect_gpu, detect_gpu_or_raise

__all__ = [
    "BundleCatalogError",
    "effective_bundle_cfg_for_preset",
    "raw_bundle_cfg",
    "resolve_effective_bundle_cfg",
    "variant_dir_name",
]

_SOURCE_KEYS = frozenset({"zip", "path", "git", "ref"})


class BundleCatalogError(RuntimeError):
    """Invalid or missing bundle configuration in models.yaml."""


def raw_bundle_cfg(preset: Preset) -> dict[str, Any]:
    raw = preset.raw.get("bundle") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _effective_cfg(raw: dict[str, Any], *, runtime_env: str) -> dict[str, Any]:
    cfg = {
        k: v
        for k, v in raw.items()
        if k not in _SOURCE_KEYS
    }
    for key in _SOURCE_KEYS:
        if key in raw:
            cfg[key] = raw[key]
    cfg["runtime_env"] = runtime_env
    cfg["host_python_minor"] = host_python_minor()
    return cfg


def resolve_effective_bundle_cfg(
    preset: Preset,
    *,
    gpu: GpuInfo | None = None,
    require_gpu: bool = True,
) -> tuple[dict[str, Any], str]:
    """Return (bundle cfg, runtime env key ``sm*-cu*-…-pyNNN`` for native selection)."""
    raw = raw_bundle_cfg(preset)
    if not any(raw.get(k) for k in _SOURCE_KEYS):
        raise BundleCatalogError(
            f"Preset {preset.name!r} has no bundle source in models.yaml. "
            "Set one of: bundle.zip, bundle.path, bundle.git"
        )

    if require_gpu:
        gpu = gpu or detect_gpu_or_raise()
        runtime_env = variant_dir_name(gpu)
    else:
        gpu = gpu or detect_gpu()
        runtime_env = variant_dir_name(gpu) if gpu else "unknown"

    return _effective_cfg(raw, runtime_env=runtime_env), runtime_env


def effective_bundle_cfg_for_preset(
    preset: Preset,
    *,
    gpu: GpuInfo | None = None,
) -> dict[str, Any]:
    cfg, _ = resolve_effective_bundle_cfg(preset, gpu=gpu, require_gpu=False)
    return cfg
