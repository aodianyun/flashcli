"""Active bundle context (set by flashcli host during infer)."""

from __future__ import annotations

import os

from flashcli_bundle.manifest import BundleManifest

_ACTIVE_BUNDLE: BundleManifest | None = None


def active_bundle() -> BundleManifest | None:
    return _ACTIVE_BUNDLE


def set_active_bundle(bundle: BundleManifest | None) -> None:
    """Register the bundle currently on ``PYTHONPATH`` (host calls during activate)."""
    global _ACTIVE_BUNDLE
    _ACTIVE_BUNDLE = bundle
    if bundle is None:
        os.environ.pop("FLASHCLI_ACTIVE_BUNDLE", None)
        os.environ.pop("FLASHCLI_ACTIVE_RUNTIME", None)
        return
    root = str(bundle.bundle_root.resolve())
    os.environ["FLASHCLI_ACTIVE_BUNDLE"] = root
    os.environ["FLASHCLI_ACTIVE_RUNTIME"] = root
