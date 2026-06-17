"""Standalone Python install paths (host sync / python_install only)."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli import config

_ENV_LOADED = False


def bundle_python_root() -> Path:
    override = os.environ.get("FLASHCLI_PYTHON_ROOT", "").strip()
    if override:
        return Path(override).expanduser()
    return config.FLASHCLI_HOME / "python"


def bundle_python_env_file() -> Path:
    override = os.environ.get("FLASHCLI_PYTHON_ENV", "").strip()
    if override:
        return Path(override).expanduser()
    return config.FLASHCLI_HOME / "python-runtime.env"


def load_python_env_file() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    path = bundle_python_env_file()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val:
                os.environ.setdefault(key, val)
    _ENV_LOADED = True
