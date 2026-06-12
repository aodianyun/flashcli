"""Tests for flashcli-bundle install spec into bundle venv."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flashcli.deps import flashcli_bundle_pip_spec


def test_flashcli_bundle_pip_spec_from_install_env(
    monkeypatch, tmp_path: Path
) -> None:
    import flashcli_bundle

    monkeypatch.setattr(
        flashcli_bundle,
        "__file__",
        str(tmp_path / "site-packages" / "flashcli_bundle" / "__init__.py"),
    )
    monkeypatch.setattr("flashcli.config.FLASHCLI_HOME", tmp_path)
    monkeypatch.setattr("flashcli.deps._pip_spec_from_direct_url", lambda *a, **k: None)
    (tmp_path / "install.env").write_text(
        "FLASHCLI_INSTALL_REPO=https://gitee.com/aodiansoft/flashcli.git\n"
        "FLASHCLI_INSTALL_REF=xzl-dev\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("FLASHCLI_INSTALL_REPO", raising=False)
    monkeypatch.delenv("FLASHCLI_INSTALL_REF", raising=False)

    spec = flashcli_bundle_pip_spec()
    assert "flashcli-bundle @ git+" in spec
    assert "xzl-dev" in spec
    assert "#subdirectory=flashcli-bundle" in spec


def test_flashcli_bundle_pip_spec_editable_repo(tmp_path: Path, monkeypatch) -> None:
    bundle_root = tmp_path / "flashcli-bundle"
    src = bundle_root / "src" / "flashcli_bundle"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (bundle_root / "pyproject.toml").write_text(
        'name = "flashcli-bundle"\n', encoding="utf-8"
    )

    import flashcli_bundle

    monkeypatch.setattr(flashcli_bundle, "__file__", str(src / "__init__.py"))
    monkeypatch.setattr(
        "flashcli.deps._pip_spec_from_direct_url",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "flashcli.deps._load_persisted_install_env",
        lambda: None,
    )
    monkeypatch.delenv("FLASHCLI_INSTALL_REPO", raising=False)

    spec = flashcli_bundle_pip_spec()
    assert spec == str(bundle_root.resolve())


def test_flashcli_bundle_pip_spec_missing_source(monkeypatch) -> None:
    monkeypatch.setattr("flashcli.deps._load_persisted_install_env", lambda: None)
    monkeypatch.setattr("flashcli.deps._pip_spec_from_direct_url", lambda *a, **k: None)
    monkeypatch.delenv("FLASHCLI_INSTALL_REPO", raising=False)

    import flashcli_bundle

    monkeypatch.setattr(
        flashcli_bundle,
        "__file__",
        "/tmp/site-packages/flashcli_bundle/__init__.py",
    )

    with pytest.raises(RuntimeError, match="Cannot resolve flashcli-bundle"):
        flashcli_bundle_pip_spec()
