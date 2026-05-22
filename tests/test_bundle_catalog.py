"""Unit tests for models.yaml bundle resolution (single source per preset)."""

from __future__ import annotations

import pytest

from flashcli.bundle.catalog import (
    BundleCatalogError,
    resolve_effective_bundle_cfg,
    variant_dir_name,
)
from flashcli.bundle.runtime_env import host_python_minor
from flashcli.models.registry import Preset
from flashcli.runtime.detect import GpuInfo


def _gpu(sm: str = "89", cuda: str = "124") -> GpuInfo:
    return GpuInfo(
        sm=sm,
        cuda_tag=cuda,
        os_name="linux",
        arch="x86_64",
        recommended_torch_index="cu124",
        gpu_name="Test GPU",
    )


def _preset(raw: dict) -> Preset:
    return Preset(name="test", raw=raw)


def test_single_zip_cfg():
    p = _preset({"bundle": {"zip": "https://example.com/bundle.zip"}})
    cfg, env = resolve_effective_bundle_cfg(p, gpu=_gpu(), require_gpu=False)
    assert cfg["zip"] == "https://example.com/bundle.zip"
    assert env.endswith(f"-py{host_python_minor()}")


def test_missing_source_raises():
    p = _preset({"bundle": {"description": "x"}})
    with pytest.raises(BundleCatalogError):
        resolve_effective_bundle_cfg(p, require_gpu=False)


def test_runtime_env_includes_python():
    p = _preset({"bundle": {"path": "bundles/pi05_libero"}})
    _, env = resolve_effective_bundle_cfg(p, gpu=_gpu(sm="89", cuda="124"))
    assert env == variant_dir_name(_gpu())
