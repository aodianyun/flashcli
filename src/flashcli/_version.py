"""Package version — single source: pyproject.toml [project].version."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _read_pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    if sys.version_info >= (3, 11):
        import tomllib

        data = tomllib.loads(text)
    else:
        import tomli

        data = tomli.loads(text)
    return str(data["project"]["version"])


def resolve_version() -> str:
    try:
        return version("flashcli")
    except PackageNotFoundError:
        return _read_pyproject_version()


__version__ = resolve_version()
