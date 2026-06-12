"""Ensure flashcli-bundle is not declared as a PyPI dependency of flashcli."""

from __future__ import annotations

from pathlib import Path


def test_pyproject_does_not_pip_depend_on_flashcli_bundle() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies = ["):
            in_deps = True
            continue
        if in_deps:
            if stripped == "]":
                break
            assert "flashcli-bundle" not in stripped, (
                "flashcli-bundle must not be in [project].dependencies — "
                "it is git-only (install.sh / deps.flashcli_bundle_pip_spec)"
            )
