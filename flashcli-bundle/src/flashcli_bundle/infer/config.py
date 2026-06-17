"""Backward-compat re-export; prefer ``flashcli_bundle.paths``."""

from __future__ import annotations

from flashcli_bundle.paths import (
    BUNDLES_DIR,
    CACHE_DIR,
    FLASHCLI_HOME,
    FLASHHUB_API_BASE,
    MODELS_DIR,
    RUNTIMES_DIR,
    SKIP_AUTO_INSTALL_ENV,
    package_root,
    skip_auto_install,
)

__all__ = [
    "BUNDLES_DIR",
    "CACHE_DIR",
    "FLASHCLI_HOME",
    "FLASHHUB_API_BASE",
    "MODELS_DIR",
    "RUNTIMES_DIR",
    "SKIP_AUTO_INSTALL_ENV",
    "package_root",
    "skip_auto_install",
]
