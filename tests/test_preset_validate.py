"""Tests for manifest-first preset validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flashcli.bundle.manifest import load_bundle_manifest_data
from flashcli.bundle.preset_validate import (
    fetch_manifest_for_preset,
    validate_preset_before_sync,
)
from flashcli.bundle.variants import BundleVariantError, validate_required_variant
from flashcli.models.preset_ref import resolve_run_target
from flashcli.models.registry import Preset


def _multi_variant_manifest(tmp_path: Path):
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "qwen_nvfp4",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "variants": {
            "qwen3": {},
            "qwen36": {},
        },
        "runtime": {"sm120-cu130-linux-x86_64-py312": "runtime/x"},
    }
    (tmp_path / "flashcli-bundle.json").write_text(json.dumps(data), encoding="utf-8")
    return load_bundle_manifest_data(data, bundle_root=tmp_path)


def test_validate_required_variant_rejects_missing_at_variant(tmp_path: Path) -> None:
    manifest = _multi_variant_manifest(tmp_path)
    preset = Preset(
        name="flashcli-bundle/qwen_nvfp4:1.0.1",
        raw={"bundle": {"repo": "https://flashhub.example/qwen_nvfp4:1.0.1"}},
    )
    with pytest.raises(BundleVariantError, match="qwen3.*qwen36"):
        validate_required_variant(preset, manifest)


def test_validate_required_variant_accepts_at_variant(tmp_path: Path) -> None:
    manifest = _multi_variant_manifest(tmp_path)
    preset = Preset(
        name="flashcli-bundle/qwen_nvfp4:1.0.1@qwen36",
        raw={
            "bundle": {"repo": "https://flashhub.example/qwen_nvfp4:1.0.1"},
            "bundle_variant": "qwen36",
        },
    )
    validate_required_variant(preset, manifest)


def test_fetch_manifest_uses_local_bundle(tmp_path: Path) -> None:
    manifest = _multi_variant_manifest(tmp_path)
    preset = Preset(
        name="local:qwen_nvfp4@qwen36",
        raw={"bundle": {"local_root": str(tmp_path)}, "bundle_variant": "qwen36"},
    )
    fetched = fetch_manifest_for_preset(preset, bundle_path=tmp_path)
    assert fetched.name == manifest.name


def test_fetch_manifest_downloads_when_no_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "pi05_libero",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "runtime": {"sm89-cu124-linux-x86_64-py312": "runtime/x"},
    }
    repo = "https://flashhub.example/pi05/1.0.4"
    preset = Preset(
        name="flashcli-bundle/pi05_libero:1.0.4",
        raw={"bundle": {"repo": repo}},
        cache_key="pi05_libero/1.0.4",
    )
    monkeypatch.setattr(
        "flashcli.bundle.preset_validate.read_preset_marker",
        lambda _p: {},
    )
    monkeypatch.setattr(
        "flashcli.bundle.preset_validate.download_manifest_from_repo",
        lambda _repo, _dest, **kw: fresh,
    )
    manifest = fetch_manifest_for_preset(preset, quiet=True)
    assert manifest.name == "pi05_libero"


def test_resolve_run_target_local_bundle_positional() -> None:
    from flashcli.models.preset_ref import local_bundle_id

    root = Path(__file__).resolve().parents[1] / "bundles" / "qwen_nvfp4"
    preset, bundle_path = resolve_run_target("bundles/qwen_nvfp4@qwen36")
    assert bundle_path == root.resolve()
    assert preset.bundle_variant == "qwen36"
    expected_id = local_bundle_id(root)
    assert expected_id.startswith("qwen_nvfp4-local-")
    assert preset.cache_key == f"{expected_id}/local@qwen36"
    assert preset.name == f"local:{expected_id}@qwen36"


def test_local_dist_bundles_do_not_share_cache_key(tmp_path: Path) -> None:
    from flashcli.models.preset_ref import resolve_local_bundle_preset

    def _write_dist(parent: Path, name: str) -> Path:
        dist = parent / "dist"
        dist.mkdir(parents=True)
        (dist / "flashcli-bundle.json").write_text(
            json.dumps({"name": name}),
            encoding="utf-8",
        )
        return dist

    a = _write_dist(tmp_path / "wan22", "wan22")
    b = _write_dist(tmp_path / "pi05_libero", "pi05_libero")
    key_a = resolve_local_bundle_preset(a, None).cache_key
    key_b = resolve_local_bundle_preset(b, None).cache_key
    assert key_a != key_b
    assert key_a.startswith("wan22-local-")
    assert key_b.startswith("pi05_libero-local-")
    assert key_a.endswith("/local")
    assert key_b.endswith("/local")
    # Same path resolves to a stable key.
    assert resolve_local_bundle_preset(a, None).cache_key == key_a


def test_resolve_run_target_flashhub_ref() -> None:
    preset, bundle_path = resolve_run_target("flashcli-bundle/qwen_nvfp4:1.0.1@qwen36")
    assert bundle_path is None
    assert preset.bundle_variant == "qwen36"


def test_validate_preset_before_sync_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _multi_variant_manifest(tmp_path)
    preset = Preset(
        name="local:qwen_nvfp4@qwen36",
        raw={"bundle": {"local_root": str(tmp_path)}, "bundle_variant": "qwen36"},
    )
    monkeypatch.setattr(
        "flashcli.bundle.preset_validate.run_preflight",
        lambda _m: None,
    )
    manifest = validate_preset_before_sync(preset, bundle_path=tmp_path)
    assert manifest.name == "qwen_nvfp4"
