"""Paths and environment flags for flashcli."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli._version import __version__

FLASHCLI_HOME = Path(
    os.environ.get("FLASHCLI_HOME", Path.home() / ".flashcli")
).expanduser()
BUNDLES_DIR = Path(
    os.environ.get("FLASHCLI_BUNDLES_DIR", FLASHCLI_HOME / "bundles")
).expanduser()
MODELS_DIR = Path(
    os.environ.get("FLASHCLI_MODELS_DIR", FLASHCLI_HOME / "models")
).expanduser()
CACHE_DIR = FLASHCLI_HOME / "cache" / "downloads"
RUNTIMES_DIR = Path(
    os.environ.get("FLASHCLI_RUNTIMES_DIR", FLASHCLI_HOME / "runtimes")
).expanduser()
CONFIG_FILE = FLASHCLI_HOME / "config.yaml"

SKIP_AUTO_INSTALL_ENV = "FLASHCLI_SKIP_AUTO_INSTALL"

_DEFAULT_FLASHHUB_API = "https://flashhub-api.aodianyun.com/api/v1/repos"

FLASHHUB_API_BASE = os.environ.get("FLASHCLI_FLASHHUB_API", _DEFAULT_FLASHHUB_API).strip().rstrip(
    "/"
) or _DEFAULT_FLASHHUB_API

_PKG_DIR = Path(__file__).resolve().parent


def package_root() -> Path:
    """Directory for resolving relative paths (repo root when developing)."""
    repo = _PKG_DIR.parent.parent
    if (repo / "bundles").is_dir() or (repo / "src").is_dir():
        return repo.resolve()
    return _PKG_DIR.resolve()


def skip_auto_install() -> bool:
    return os.environ.get(SKIP_AUTO_INSTALL_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
