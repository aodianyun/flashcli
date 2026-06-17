"""Package version — single source: pyproject.toml [project].version."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _read_dist_info_version(site_packages: Path) -> str | None:
    """Read version from ``flashcli-*.dist-info/METADATA`` (wheel install layout)."""
    for dist_info in site_packages.glob("flashcli-*.dist-info"):
        metadata = dist_info / "METADATA"
        if not metadata.is_file():
            continue
        for line in metadata.read_text(encoding="utf-8").splitlines():
            if line.startswith("Version:"):
                ver = line.split(":", 1)[1].strip()
                if ver:
                    return ver
    return None


def _read_pyproject_version() -> str:
    pkg_dir = Path(__file__).resolve().parent
    pyproject = pkg_dir.parent.parent / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        if sys.version_info >= (3, 11):
            import tomllib

            data = tomllib.loads(text)
        else:
            import tomli

            data = tomli.loads(text)
        return str(data["project"]["version"])

    dist_ver = _read_dist_info_version(pkg_dir.parent)
    if dist_ver:
        return dist_ver

    raise PackageNotFoundError("flashcli version not found")


def resolve_version() -> str:
    try:
        return version("flashcli")
    except PackageNotFoundError:
        return _read_pyproject_version()


__version__ = resolve_version()
