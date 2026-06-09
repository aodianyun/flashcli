"""Tests for bundle environment preflight."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flashcli.bundle.manifest import load_bundle_manifest_data
from flashcli.bundle.preflight import BundleEnvironmentError, run_preflight
from flashcli.runtime.detect import GpuInfo


def _gpu(**kwargs) -> GpuInfo:
    defaults = dict(
        gpu_name="Test GPU",
        sm="120",
        cuda_tag="130",
        os_name="linux",
        arch="x86_64",
    )
    defaults.update(kwargs)
    return GpuInfo(**defaults)


def _manifest(tmp_path: Path) -> Path:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "name": "test",
        "python_abi": "312",
        "runtime": {
            "sm120-cu130-linux-x86_64-py312": "runtime/sm120-cu130-linux-x86_64-py312"
        },
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "python_dependencies": {
            "torch": {"package": "torch", "index": "cu128"},
            "pip": ["numpy"],
        },
    }
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "flashcli-bundle.json").write_text(json.dumps(data), encoding="utf-8")
    return root


def test_preflight_match(tmp_path: Path, monkeypatch) -> None:
    root = _manifest(tmp_path)
    manifest = load_bundle_manifest_data(
        json.loads((root / "flashcli-bundle.json").read_text()),
        bundle_root=root,
    )
    monkeypatch.setattr(
        "flashcli.bundle.preflight.resolve_python_for_minor",
        lambda _abi: Path("/usr/bin/python3.12"),
    )
    result = run_preflight(manifest, gpu=_gpu())
    assert result.env_key == "sm120-cu130-linux-x86_64-py312"


def test_preflight_env_mismatch(tmp_path: Path) -> None:
    root = _manifest(tmp_path)
    manifest = load_bundle_manifest_data(
        json.loads((root / "flashcli-bundle.json").read_text()),
        bundle_root=root,
    )
    with pytest.raises(BundleEnvironmentError, match="does not support"):
        run_preflight(manifest, gpu=_gpu(sm="89", cuda_tag="124"))
