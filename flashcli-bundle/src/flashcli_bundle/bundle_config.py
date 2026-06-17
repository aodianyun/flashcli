"""Read model settings from ``flashcli-bundle.json``."""

from __future__ import annotations

from typing import Any

from flashcli_bundle.manifest import BundleManifest


def bundle_dict(bundle: BundleManifest, key: str) -> dict[str, Any]:
    raw = bundle.raw.get(key)
    return dict(raw) if isinstance(raw, dict) else {}


def bundle_list(bundle: BundleManifest, key: str) -> list[Any]:
    raw = bundle.raw.get(key)
    return list(raw) if isinstance(raw, list) else []
