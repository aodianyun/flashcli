"""Read model settings from ``flashcli-bundle.json`` only (not models.yaml)."""

from __future__ import annotations

from typing import Any

from flashcli.bundle.manifest import BundleManifest


def bundle_dict(bundle: BundleManifest, key: str) -> dict[str, Any]:
    raw = bundle.raw.get(key)
    return dict(raw) if isinstance(raw, dict) else {}


def bundle_list(bundle: BundleManifest, key: str) -> list[Any]:
    raw = bundle.raw.get(key)
    return list(raw) if isinstance(raw, list) else []


def bundle_defaults(bundle: BundleManifest) -> dict[str, Any]:
    return bundle_dict(bundle, "defaults")


def bundle_requires(bundle: BundleManifest) -> dict[str, Any]:
    return bundle_dict(bundle, "requires")


def bundle_allowed_sms(bundle: BundleManifest) -> set[str] | None:
    sm_list = bundle_requires(bundle).get("sm")
    if not isinstance(sm_list, list):
        return None
    return {str(s) for s in sm_list}


def bundle_native_runtime(bundle: BundleManifest) -> bool:
    """Whether the bundle ships FlashRT CUDA kernels (default True)."""
    raw = bundle.raw.get("native_runtime", True)
    return raw is not False
