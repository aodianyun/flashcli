"""Tests for catalog bundle.repo resolution."""

from __future__ import annotations

from flashcli.bundle.catalog import (
    BundleCatalogError,
    effective_bundle_cfg_for_preset,
    repo_url_for_preset,
)
from flashcli.models.registry import Preset


def _preset(raw: dict) -> Preset:
    return Preset(name="test", raw=raw)


def test_repo_url_for_preset() -> None:
    p = _preset({"bundle": {"repo": "https://flashhub.example/repo/1/versions/2"}})
    assert repo_url_for_preset(p) == "https://flashhub.example/repo/1/versions/2"


def test_missing_repo_raises() -> None:
    p = _preset({"bundle": {}})
    try:
        repo_url_for_preset(p)
        assert False, "expected BundleCatalogError"
    except BundleCatalogError:
        pass


def test_effective_cfg_includes_runtime_env() -> None:
    p = _preset({"bundle": {"repo": "https://example.com/repo"}})
    cfg = effective_bundle_cfg_for_preset(p)
    assert cfg["repo"] == "https://example.com/repo"
    assert "runtime_env" in cfg
