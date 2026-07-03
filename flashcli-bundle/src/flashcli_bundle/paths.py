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
_PYTHON_STANDALONE_NAMESPACE = "flashcli-bundle"
_PYTHON_STANDALONE_BUNDLE = "python-standalone"
_DEFAULT_PYTHON_STANDALONE_VERSION = "1.0.0"


def flashhub_api_base() -> str:
    """Resolved FlashHub API base (``FLASHCLI_FLASHHUB_API``)."""
    raw = os.environ.get("FLASHCLI_FLASHHUB_API", _DEFAULT_FLASHHUB_API).strip().rstrip("/")
    return raw or _DEFAULT_FLASHHUB_API


# Import-time snapshot for legacy imports; prefer flashhub_api_base() when env may change.
FLASHHUB_API_BASE = flashhub_api_base()


def flashhub_repo_url(namespace: str, bundle: str, version: str) -> str:
    """Build FlashHub repo API URL: ``{FLASHHUB_API_BASE}/{namespace}/{bundle}:{version}``."""
    ns = namespace.strip().strip("/")
    name = bundle.strip().strip("/")
    ver = version.strip()
    if not ns or not name or not ver:
        raise ValueError(
            f"Invalid FlashHub repo parts: namespace={namespace!r} bundle={bundle!r} version={version!r}"
        )
    return f"{flashhub_api_base().rstrip('/')}/{ns}/{name}:{ver}"


def default_python_standalone_repo_url() -> str:
    """Default python-standalone repo under the same FlashHub API base as bundles."""
    ver = (
        os.environ.get("FLASHCLI_PYTHON_STANDALONE_VERSION", _DEFAULT_PYTHON_STANDALONE_VERSION)
        .strip()
        or _DEFAULT_PYTHON_STANDALONE_VERSION
    )
    return flashhub_repo_url(_PYTHON_STANDALONE_NAMESPACE, _PYTHON_STANDALONE_BUNDLE, ver)


def python_standalone_repo_url() -> str | None:
    """FlashHub repo for standalone Python tarballs (``FLASHCLI_PYTHON_REPO``)."""
    raw = os.environ.get("FLASHCLI_PYTHON_REPO", "").strip()
    if raw.lower() in ("0", "false", "no", "off"):
        return None
    if raw:
        return raw.rstrip("/")
    return default_python_standalone_repo_url()


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
