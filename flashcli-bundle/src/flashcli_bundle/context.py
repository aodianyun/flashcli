"""Active bundle context (set by flashcli host during infer)."""

from __future__ import annotations

from flashcli_bundle.manifest import BundleManifest

_ACTIVE_BUNDLE: BundleManifest | None = None


def active_bundle() -> BundleManifest | None:
    return _ACTIVE_BUNDLE


def set_active_bundle(bundle: BundleManifest | None) -> None:
    """Register the bundle currently on ``sys.path`` (in-memory only)."""
    global _ACTIVE_BUNDLE
    _ACTIVE_BUNDLE = bundle
