"""Tests for bundle root resolution after runtime prepare."""

from __future__ import annotations

from pathlib import Path

from flashcli.bundle.layout import is_bundle_root
from flashcli.bundle.marker import write_preset_marker
from flashcli.bundle.resolve import resolve_bundle_root
from flashcli.models.registry import Preset


def _fake_preset(name: str = "pi05_libero") -> Preset:
    return Preset(
        name=name,
        raw={
            "engine": "model_bundle",
            "bundle": {"repo": "https://example.test/bundle/1.0.0"},
        },
    )


def test_resolve_bundle_root_from_preset_marker(monkeypatch, tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    (bundle_root / "flashcli-bundle.json").write_text("{}", encoding="utf-8")
    assert is_bundle_root(bundle_root)

    monkeypatch.setattr("flashcli.config.BUNDLES_DIR", tmp_path / "bundles")
    preset = _fake_preset()
    write_preset_marker(
        preset,
        {
            "source": "repo",
            "repo": "https://example.test/bundle/1.0.0",
            "runtime_id": "pi05_libero-deadbeef",
            "bundle_root": str(bundle_root),
            "env_key": "sm89-cu124-linux-x86_64-py312",
        },
    )

    root = resolve_bundle_root(preset)
    assert root == bundle_root.resolve()
