"""Tests for host flashcli import isolation (bundle re-exec)."""

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


def test_host_import_shim_does_not_expose_site_packages(monkeypatch, tmp_path):
    site = tmp_path / "site-packages"
    pkg = site / "flashcli"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (site / "huggingface_hub").mkdir()
    (site / "huggingface_hub" / "__init__.py").write_text("", encoding="utf-8")

    home = tmp_path / "flashcli-home"
    monkeypatch.setattr(shared.config, "FLASHCLI_HOME", home)
    monkeypatch.setattr(shared, "installed_flashcli_package_root", lambda: pkg)
    monkeypatch.setattr(shared, "editable_flashcli_src", lambda: None)

    import_root = shared.host_flashcli_import_root()
    assert import_root != site.resolve()
    assert import_root == (home / "host-import").resolve()
    assert (import_root / "flashcli").resolve() == pkg.resolve()
    assert not (import_root / "huggingface_hub").exists()


def test_prepend_pythonpath():
    env: dict[str, str] = {}
    shared.prepend_pythonpath(env, "/a")
    assert env["PYTHONPATH"] == "/a"
    shared.prepend_pythonpath(env, "/b")
    assert env["PYTHONPATH"] == f"/b{os.pathsep}/a"
