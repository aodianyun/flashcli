"""Tests for bundle Python auto-install."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from flashcli.bundle.python_install import (
    auto_install_bundle_python_enabled,
    ensure_python_for_minor,
    load_python_env_file,
    standalone_download_url,
)


def test_standalone_url_linux_x86_64(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "flashcli.bundle.python_install.platform.machine",
        lambda: "x86_64",
    )
    monkeypatch.setattr(
        "flashcli.bundle.python_install.resolve_standalone_asset",
        lambda _minor, _triplet, **_: type("A", (), {
            "url": "https://example.test/cpython-3.12.10+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz"
        })(),
    )
    url = standalone_download_url("312")
    assert "cpython-3.12" in url
    assert "x86_64-unknown-linux-gnu-install_only.tar.gz" in url


def test_standalone_url_darwin_arm64(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        "flashcli.bundle.python_install.platform.machine",
        lambda: "arm64",
    )
    monkeypatch.setattr(
        "flashcli.bundle.python_install.resolve_standalone_asset",
        lambda _minor, _triplet, **_: type("A", (), {
            "url": "https://example.test/cpython-3.12.10+20260602-aarch64-apple-darwin-install_only.tar.gz"
        })(),
    )
    url = standalone_download_url("312")
    assert "aarch64-apple-darwin-install_only.tar.gz" in url


def test_auto_install_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON", raising=False)
    assert auto_install_bundle_python_enabled() is True


def test_auto_install_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON", "0")
    assert auto_install_bundle_python_enabled() is False


def test_ensure_python_skips_install_when_disabled(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON", "0")
    monkeypatch.setenv("FLASHCLI_HOME", str(tmp_path))
    monkeypatch.setattr(
        "flashcli.bundle.native_validate.resolve_python_for_minor",
        lambda _abi: None,
    )
    assert ensure_python_for_minor("312", auto_install=False) is None


def test_ensure_python_uses_existing(monkeypatch, tmp_path: Path) -> None:
    py = tmp_path / "python3.12"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    monkeypatch.setattr(
        "flashcli.bundle.native_validate.resolve_python_for_minor",
        lambda _abi: py,
    )
    with patch("flashcli.bundle.python_install.install_standalone_python") as install_mock:
        assert ensure_python_for_minor("312") == py
        install_mock.assert_not_called()


def test_load_python_env_file(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "python-runtime.env"
    py = tmp_path / "py312"
    env_file.write_text(f"export FLASHCLI_PY312_BIN={py}\n", encoding="utf-8")
    monkeypatch.setenv("FLASHCLI_PYTHON_ENV", str(env_file))
    monkeypatch.delenv("FLASHCLI_PY312_BIN", raising=False)

    import flashcli.bundle.python_install as mod

    mod._ENV_LOADED = False
    load_python_env_file()
    assert os.environ["FLASHCLI_PY312_BIN"] == str(py)


def test_ensure_python_triggers_install(monkeypatch, tmp_path: Path) -> None:
    py = tmp_path / "standalone" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    monkeypatch.setattr(
        "flashcli.bundle.native_validate.resolve_python_for_minor",
        lambda _abi: None,
    )
    with patch(
        "flashcli.bundle.python_install.install_standalone_python",
        return_value=py,
    ) as install_mock:
        assert ensure_python_for_minor("312") == py
        install_mock.assert_called_once_with("312", quiet=False)
