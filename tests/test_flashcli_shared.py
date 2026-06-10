"""Tests for shared flashcli layout (one copy per version + python_abi)."""

from __future__ import annotations

from pathlib import Path

from flashcli import __version__
import flashcli.runtime.flashcli_shared as shared


def test_shared_root_includes_version_and_abi(monkeypatch, tmp_path):
    monkeypatch.setattr(shared.config, "FLASHCLI_HOME", tmp_path)
    root = shared.shared_flashcli_root("312")
    assert root == tmp_path / "share" / "flashcli" / __version__ / "312"


def test_editable_src_when_repo_layout(monkeypatch, tmp_path):
    repo = tmp_path / "flashcli"
    (repo / "src" / "flashcli").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='flashcli'\n", encoding="utf-8")
    monkeypatch.setattr(shared.config, "package_root", lambda: repo)
    assert shared.is_editable_flashcli()
    assert shared.flashcli_pythonpath(python_abi="312") == str((repo / "src").resolve())


def test_shared_pythonpath_when_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(shared.config, "FLASHCLI_HOME", tmp_path)
    monkeypatch.setattr(
        shared.config,
        "package_root",
        lambda: tmp_path / "noproj",
    )
    root = shared.shared_flashcli_root("312")
    root.mkdir(parents=True)
    (root / "flashcli").mkdir()
    assert shared.flashcli_pythonpath(python_abi="312") == str(root)
