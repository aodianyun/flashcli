"""Tests for flashcli bundle purge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flashcli.bundle.purge import clean_all_cached, clean_preset_cache
from flashcli_bundle import paths as config
from flashcli_bundle.marker import write_preset_marker, write_runtime_marker
from flashcli_bundle.preset import Preset


@pytest.fixture
def flashcli_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "flashcli-home"
    monkeypatch.setenv("FLASHCLI_HOME", str(home))
    config.FLASHCLI_HOME = home
    config.BUNDLES_DIR = home / "bundles"
    config.MODELS_DIR = home / "models"
    config.RUNTIMES_DIR = home / "runtimes"
    config.CACHE_DIR = home / "cache" / "downloads"
    return home


def test_purge_preset_removes_runtime_weights_and_marker(flashcli_home: Path) -> None:
    preset = Preset(
        name="flashcli-bundle/demo:1.0.0",
        raw={"engine": "model_bundle", "bundle": {"repo": "https://example/repo"}},
        cache_key="demo/1.0.0",
    )
    runtime_id = "runtime-demo"
    bundle_root = flashcli_home / "runtimes" / runtime_id / "bundle"
    bundle_root.mkdir(parents=True)
    (bundle_root / "flashcli-bundle.json").write_text(
        json.dumps({"format": "flashcli-model-bundle", "format_version": 3}),
        encoding="utf-8",
    )
    write_runtime_marker(runtime_id, {"runtime_id": runtime_id})
    write_preset_marker(
        preset,
        {
            "ref": preset.name,
            "runtime_id": runtime_id,
            "bundle_root": str(bundle_root),
            "repo": "https://example/repo",
        },
    )

    weights = config.MODELS_DIR / "demo/1.0.0" / "checkpoint"
    weights.mkdir(parents=True)
    (weights / "model.safetensors").write_bytes(b"x")

    marker_dir = config.BUNDLES_DIR / "demo/1.0.0"
    assert marker_dir.is_dir()

    removed = clean_preset_cache(preset)
    assert str(config.MODELS_DIR / "demo/1.0.0") in removed
    assert str(marker_dir) in removed
    assert str(config.RUNTIMES_DIR / runtime_id) in removed
    assert not weights.exists()
    assert not marker_dir.exists()
    assert not (config.RUNTIMES_DIR / runtime_id).exists()


def test_purge_preset_removes_extra_weights_cache_name(flashcli_home: Path) -> None:
    preset = Preset(
        name="flashcli-bundle/demo:1.0.0@mtp",
        raw={
            "engine": "model_bundle",
            "bundle": {"repo": "https://example/repo"},
            "bundle_variant": "mtp",
        },
        cache_key="demo/1.0.0@mtp",
    )
    runtime_id = "runtime-demo-mtp"
    bundle_root = flashcli_home / "runtimes" / runtime_id / "bundle"
    bundle_root.mkdir(parents=True)
    manifest = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "variants": {
            "mtp": {
                "extra_weights": {
                    "sidecar": {
                        "source": "huggingface",
                        "repo": "org/sidecar",
                        "cache_name": "demo/1.0.0@mtp/sidecar",
                    }
                }
            }
        },
    }
    (bundle_root / "flashcli-bundle.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    write_preset_marker(
        preset,
        {
            "ref": preset.name,
            "runtime_id": runtime_id,
            "bundle_root": str(bundle_root),
        },
    )

    extra = config.MODELS_DIR / "demo/1.0.0@mtp/sidecar"
    extra.mkdir(parents=True)
    (extra / "sidecar.safetensors").write_bytes(b"x")

    removed = clean_preset_cache(preset)
    assert str(config.MODELS_DIR / "demo/1.0.0@mtp") in removed
    assert not extra.exists()


def test_purge_all_cached(flashcli_home: Path) -> None:
    for sub in ("models/a", "bundles/b", "runtimes/c"):
        path = flashcli_home / sub
        path.mkdir(parents=True)
        (path / "keep").write_text("x", encoding="utf-8")

    removed = clean_all_cached()
    assert str(config.MODELS_DIR) in removed
    assert str(config.BUNDLES_DIR) in removed
    assert str(config.RUNTIMES_DIR) in removed
    assert not config.MODELS_DIR.exists()
