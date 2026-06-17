"""Regression tests for host/bundle environment isolation."""

from __future__ import annotations

import pytest

from flashcli.runtime.isolation import HostBundleIsolationError, validate_host_import_root


def test_rejects_site_packages_root(tmp_path) -> None:
    site = tmp_path / "site-packages"
    site.mkdir()
    (site / "flashcli").mkdir()
    (site / "huggingface_hub").mkdir()
    with pytest.raises(HostBundleIsolationError, match="site-packages"):
        validate_host_import_root(site)


def test_rejects_shim_with_huggingface_hub_sibling(tmp_path) -> None:
    root = tmp_path / "host-import"
    root.mkdir()
    (root / "flashcli").mkdir()
    (root / "huggingface_hub").mkdir()
    with pytest.raises(HostBundleIsolationError, match="huggingface_hub"):
        validate_host_import_root(root)


def test_accepts_editable_src_layout(tmp_path) -> None:
    src = tmp_path / "src"
    (src / "flashcli").mkdir(parents=True)
    validate_host_import_root(src)


def test_accepts_wheel_shim_layout(tmp_path) -> None:
    shim = tmp_path / "host-import"
    shim.mkdir()
    (shim / "flashcli").mkdir()
    validate_host_import_root(shim)
