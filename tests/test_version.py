"""Version is defined only in pyproject.toml."""

from __future__ import annotations

from flashcli import __version__
from flashcli._version import _read_pyproject_version


def test_version_matches_pyproject() -> None:
    assert __version__ == _read_pyproject_version()
