"""Tests for flashcli-bundle install spec into bundle venv."""

from __future__ import annotations

from pathlib import Path

import pytest

from flashcli_bundle.infer.deps import (
    _apply_git_proxy_to_vcs_spec,
    _git_clone_url,
    flashcli_bundle_pip_spec,
)


def test_flashcli_bundle_pip_spec_from_install_env(
    monkeypatch, tmp_path: Path
) -> None:
    import flashcli_bundle
    import flashcli_bundle.infer.deps as deps
    import flashcli_bundle.paths as paths

    monkeypatch.setattr(
        flashcli_bundle,
        "__file__",
        str(tmp_path / "site-packages" / "flashcli_bundle" / "__init__.py"),
    )
    monkeypatch.setattr(paths, "FLASHCLI_HOME", tmp_path)
    monkeypatch.setattr(deps, "_pip_spec_from_direct_url", lambda *a, **k: None)
    monkeypatch.setattr(deps, "apply_mirror_env", lambda: None)
    (tmp_path / "install.env").write_text(
        "FLASHCLI_INSTALL_REPO=https://gitee.com/aodiansoft/flashcli.git\n"
        "FLASHCLI_INSTALL_REF=xzl-dev\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("FLASHCLI_INSTALL_REPO", raising=False)
    monkeypatch.delenv("FLASHCLI_INSTALL_REF", raising=False)
    monkeypatch.delenv("FLASHCLI_GIT_PROXY", raising=False)

    spec = flashcli_bundle_pip_spec()
    assert "flashcli-bundle[infer] @ git+" in spec
    assert "gitee.com/aodiansoft/flashcli.git@xzl-dev" in spec
    assert "#subdirectory=flashcli-bundle" in spec
    assert "gh-proxy" not in spec


def test_flashcli_bundle_pip_spec_applies_git_proxy_to_github(
    monkeypatch, tmp_path: Path
) -> None:
    import flashcli_bundle
    import flashcli_bundle.infer.deps as deps
    import flashcli_bundle.paths as paths

    monkeypatch.setattr(
        flashcli_bundle,
        "__file__",
        str(tmp_path / "site-packages" / "flashcli_bundle" / "__init__.py"),
    )
    monkeypatch.setattr(paths, "FLASHCLI_HOME", tmp_path)
    monkeypatch.setattr(deps, "_pip_spec_from_direct_url", lambda *a, **k: None)
    monkeypatch.setattr(deps, "apply_mirror_env", lambda: None)
    (tmp_path / "install.env").write_text(
        "FLASHCLI_INSTALL_REPO=https://github.com/aodianyun/flashcli.git\n"
        "FLASHCLI_INSTALL_REF=main\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FLASHCLI_GIT_PROXY", "https://gh-proxy.com/")
    monkeypatch.delenv("FLASHCLI_INSTALL_REPO", raising=False)
    monkeypatch.delenv("FLASHCLI_INSTALL_REF", raising=False)

    spec = flashcli_bundle_pip_spec()
    assert (
        "git+https://gh-proxy.com/https://github.com/aodianyun/flashcli.git@main"
        in spec
    )


def test_git_clone_url_and_vcs_spec_proxy(monkeypatch) -> None:
    monkeypatch.setenv("FLASHCLI_GIT_PROXY", "https://gh-proxy.com/")
    assert _git_clone_url("https://github.com/aodianyun/flashcli.git").startswith(
        "https://gh-proxy.com/https://github.com/"
    )
    assert _git_clone_url("https://gitee.com/aodiansoft/flashcli.git") == (
        "https://gitee.com/aodiansoft/flashcli.git"
    )
    proxied = _apply_git_proxy_to_vcs_spec(
        "flashcli-bundle[infer] @ git+https://github.com/aodianyun/flashcli.git@main"
        "#subdirectory=flashcli-bundle"
    )
    assert "gh-proxy.com/https://github.com/" in proxied
    assert proxied.endswith("#subdirectory=flashcli-bundle")


def test_flashcli_bundle_pip_spec_editable_repo(tmp_path: Path, monkeypatch) -> None:
    bundle_root = tmp_path / "flashcli-bundle"
    src = bundle_root / "src" / "flashcli_bundle"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (bundle_root / "pyproject.toml").write_text(
        'name = "flashcli-bundle"\n', encoding="utf-8"
    )

    import flashcli_bundle
    import flashcli_bundle.infer.deps as deps

    monkeypatch.setattr(flashcli_bundle, "__file__", str(src / "__init__.py"))
    monkeypatch.setattr(deps, "_pip_spec_from_direct_url", lambda *a, **k: None)
    monkeypatch.setattr(deps, "_load_persisted_install_env", lambda: None)
    monkeypatch.setattr(deps, "apply_mirror_env", lambda: None)
    monkeypatch.delenv("FLASHCLI_INSTALL_REPO", raising=False)

    spec = flashcli_bundle_pip_spec()
    assert spec == f"{bundle_root.resolve()}[infer]"


def test_flashcli_bundle_pip_spec_missing_source(monkeypatch) -> None:
    import flashcli_bundle
    import flashcli_bundle.infer.deps as deps

    monkeypatch.setattr(deps, "_load_persisted_install_env", lambda: None)
    monkeypatch.setattr(deps, "apply_mirror_env", lambda: None)
    monkeypatch.setattr(deps, "_pip_spec_from_direct_url", lambda *a, **k: None)
    monkeypatch.delenv("FLASHCLI_INSTALL_REPO", raising=False)

    monkeypatch.setattr(
        flashcli_bundle,
        "__file__",
        "/tmp/site-packages/flashcli_bundle/__init__.py",
    )

    with pytest.raises(RuntimeError, match="Cannot resolve flashcli-bundle"):
        flashcli_bundle_pip_spec()
