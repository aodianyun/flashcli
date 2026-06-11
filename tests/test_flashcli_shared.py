"""Tests for host flashcli PYTHONPATH (single install, bundle re-exec)."""

from __future__ import annotations

import os
from pathlib import Path

import flashcli.runtime.flashcli_shared as shared


def test_editable_src_when_repo_layout(monkeypatch, tmp_path):
    repo = tmp_path / "flashcli"
    (repo / "src" / "flashcli").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='flashcli'\n", encoding="utf-8")
    monkeypatch.setattr(shared.config, "package_root", lambda: repo)
    assert shared.is_editable_flashcli()
    assert shared.host_flashcli_pythonpath() == str((repo / "src").resolve())
    assert shared.flashcli_pythonpath(python_abi="312") == str((repo / "src").resolve())


def test_host_pythonpath_uses_site_packages_parent(monkeypatch, tmp_path):
    site = tmp_path / "site-packages" / "flashcli"
    site.mkdir(parents=True)
    (site / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(shared, "installed_flashcli_pkg_dir", lambda: site)
    monkeypatch.setattr(shared, "editable_flashcli_src", lambda: None)
    assert shared.host_flashcli_pythonpath() == str(site.parent.resolve())


def test_prepend_pythonpath():
    env: dict[str, str] = {}
    shared.prepend_pythonpath(env, "/a")
    assert env["PYTHONPATH"] == "/a"
    shared.prepend_pythonpath(env, "/b")
    assert env["PYTHONPATH"] == f"/b{os.pathsep}/a"
