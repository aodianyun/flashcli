"""Paths and environment flags for flashcli (host).

Shared path constants are defined once in ``flashcli_bundle.paths`` and
re-exported here so host code keeps ``from flashcli import config``.
"""

from __future__ import annotations

from pathlib import Path

from flashcli._version import __version__
from flashcli_bundle.paths import (
    BUNDLES_DIR,
    CACHE_DIR,
    FLASHCLI_HOME,
    FLASHHUB_API_BASE,
    MODELS_DIR,
    RUNTIMES_DIR,
    SKIP_AUTO_INSTALL_ENV,
    skip_auto_install,
)

CONFIG_FILE = FLASHCLI_HOME / "config.yaml"

_PKG_DIR = Path(__file__).resolve().parent


def package_root() -> Path:
    """Directory for resolving relative paths (repo root when developing)."""
    repo = _PKG_DIR.parent.parent
    if (repo / "bundles").is_dir() or (repo / "src").is_dir():
        return repo.resolve()
    return _PKG_DIR.resolve()


__all__ = [
    "__version__",
    "BUNDLES_DIR",
    "CACHE_DIR",
    "CONFIG_FILE",
    "FLASHCLI_HOME",
    "FLASHHUB_API_BASE",
    "MODELS_DIR",
    "RUNTIMES_DIR",
    "SKIP_AUTO_INSTALL_ENV",
    "package_root",
    "skip_auto_install",
]
