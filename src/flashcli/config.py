"""Paths and environment flags for flashcli."""

from __future__ import annotations

import os
import sys
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

_PKG_DIR = Path(__file__).resolve().parent
_CATALOG_YAML = _PKG_DIR / "catalog" / "models.yaml"


def _share_models_yaml_candidates() -> list[Path]:
    if sys.platform == "win32":
        return []
    return [
        Path("/usr/share/flashcli/models/models.yaml"),
        Path("/usr/share/flashcli/models.yaml"),
    ]


def _resolve_models_yaml() -> Path:
    """Locate the bundled preset catalog (single source: ``flashcli/catalog/models.yaml``)."""
    override = os.environ.get("FLASHCLI_MODELS_YAML", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(
            f"FLASHCLI_MODELS_YAML points to a missing file: {path}"
        )

    candidates: list[Path] = [_CATALOG_YAML, *_share_models_yaml_candidates()]

    for path in candidates:
        if path.is_file():
            return path.resolve()

    raise FileNotFoundError(
        "models.yaml not found. Expected one of:\n  "
        + "\n  ".join(str(p) for p in candidates)
    )


MODELS_YAML = _resolve_models_yaml()


def package_root() -> Path:
    """Directory for resolving relative ``bundle.path`` (repo root when developing)."""
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
