"""Shared paths and flags for flashcli (host + bundle venv)."""

from __future__ import annotations

import os
from pathlib import Path

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

SKIP_AUTO_INSTALL_ENV = "FLASHCLI_SKIP_AUTO_INSTALL"

_DEFAULT_FLASHHUB_API = "https://flashhub-api.aodianyun.com/api/v1/repos"

FLASHHUB_API_BASE = os.environ.get("FLASHCLI_FLASHHUB_API", _DEFAULT_FLASHHUB_API).strip().rstrip(
    "/"
) or _DEFAULT_FLASHHUB_API


def package_root() -> Path:
    """Directory for resolving relative bundle dev paths."""
    bundle_root = os.environ.get("FLASHCLI_BUNDLE_ROOT", "").strip()
    if bundle_root:
        candidate = Path(bundle_root).expanduser().resolve().parent.parent
        if (candidate / "bundles").is_dir():
            return candidate
    here = Path(__file__).resolve().parent
    for repo in here.parents:
        if (repo / "bundles").is_dir():
            return repo
    return FLASHCLI_HOME.resolve()


def skip_auto_install() -> bool:
    return os.environ.get(SKIP_AUTO_INSTALL_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
