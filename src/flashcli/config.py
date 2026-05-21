"""Paths and environment flags for flashcli."""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.1.0"

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
CONFIG_FILE = FLASHCLI_HOME / "config.yaml"

SKIP_AUTO_INSTALL_ENV = "FLASHCLI_SKIP_AUTO_INSTALL"

# Bundled model catalog (editable install: flashcli/models/models.yaml)
_PKG_ROOT = Path(__file__).resolve().parents[2]
MODELS_YAML = _PKG_ROOT / "models" / "models.yaml"

_SHARE = Path("/usr/share/flashcli")
if not MODELS_YAML.is_file() and (_SHARE / "models.yaml").is_file():
    MODELS_YAML = _SHARE / "models.yaml"


def skip_auto_install() -> bool:
    return os.environ.get(SKIP_AUTO_INSTALL_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
