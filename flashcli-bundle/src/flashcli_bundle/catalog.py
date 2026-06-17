"""Resolve bundle sources from preset refs."""

from __future__ import annotations

from typing import Any

from flashcli_bundle.runtime_env import variant_dir_name
from flashcli_bundle.preset import Preset
from flashcli_bundle.runtime.detect import GpuInfo, detect_gpu, detect_gpu_or_raise

__all__ = [
    "BundleCatalogError",
    "effective_bundle_cfg_for_preset",
    "raw_bundle_cfg",
    "repo_url_for_preset",
    "resolve_effective_bundle_cfg",
    "variant_dir_name",
]

_SOURCE_KEYS = frozenset({"repo"})


class BundleCatalogError(RuntimeError):
    """Invalid or missing bundle configuration in preset ref."""


def raw_bundle_cfg(preset: Preset) -> dict[str, Any]:
    raw = preset.raw.get("bundle") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def repo_url_for_preset(preset: Preset) -> str:
    raw = raw_bundle_cfg(preset)
    repo = str(raw.get("repo", "")).strip()
    if not repo:
        raise BundleCatalogError(
            f"Preset {preset.name!r} has no bundle.repo. "
            "Use a FlashHub ref such as flashcli-bundle/pi05_libero:1.0.3"
        )
    return repo


def _effective_cfg(raw: dict[str, Any], *, runtime_env: str) -> dict[str, Any]:
    cfg = dict(raw)
    cfg["runtime_env"] = runtime_env
    return cfg


def resolve_effective_bundle_cfg(
    preset: Preset,
    *,
    gpu: GpuInfo | None = None,
    python_abi: str | None = None,
    require_gpu: bool = True,
) -> tuple[dict[str, Any], str]:
    """Return (bundle cfg, runtime env key ``sm*-cu*-…-pyNNN``)."""
    raw = raw_bundle_cfg(preset)
    if not any(str(raw.get(k, "")).strip() for k in _SOURCE_KEYS):
        raise BundleCatalogError(
            f"Preset {preset.name!r} has no bundle.repo. "
            "Use a FlashHub ref or a local bundle path (e.g. bundles/my_bundle@variant)."
        )

    if require_gpu:
        gpu = gpu or detect_gpu_or_raise()
    else:
        gpu = gpu or detect_gpu()

    if gpu is None or python_abi is None:
        runtime_env = "unknown"
    else:
        py = python_abi or "000"
        runtime_env = variant_dir_name(gpu, python_minor=py)

    return _effective_cfg(raw, runtime_env=runtime_env), runtime_env


def effective_bundle_cfg_for_preset(
    preset: Preset,
    *,
    gpu: GpuInfo | None = None,
    python_abi: str | None = None,
) -> dict[str, Any]:
    cfg, _ = resolve_effective_bundle_cfg(
        preset, gpu=gpu, python_abi=python_abi, require_gpu=False
    )
    return cfg
