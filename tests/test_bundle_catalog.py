"""Unit tests for models.yaml bundle.variants resolution."""

from __future__ import annotations

import pytest

from flashcli.bundle.catalog import (
    BundleVariantNotFoundError,
    catalog_variant_keys,
    has_catalog_variants,
    resolve_effective_bundle_cfg,
    variant_dir_name,
)
from flashcli.models.registry import Preset
from flashcli.runtime.detect import GpuInfo


def _gpu(sm: str = "89", cuda: str = "130") -> GpuInfo:
    return GpuInfo(
        sm=sm,
        cuda_tag=cuda,
        os_name="linux",
        arch="x86_64",
        recommended_torch_index="cu128",
        gpu_name="Test GPU",
    )


def _preset(raw: dict) -> Preset:
    return Preset(name="test", raw=raw)


def test_legacy_single_zip():
    p = _preset(
        {
            "bundle": {
                "zip": "https://example.com/a.zip",
            }
        }
    )
    cfg, env = resolve_effective_bundle_cfg(p, gpu=_gpu(), require_gpu=False)
    assert env == "sm89-cu130-linux-x86_64"
    assert cfg["zip"] == "https://example.com/a.zip"
    assert not has_catalog_variants(p)


def test_catalog_variant_exact_match():
    p = _preset(
        {
            "bundle": {
                "variants": {
                    "sm89-cu130-linux-x86_64": {
                        "zip": "https://example.com/sm89.zip",
                    },
                }
            }
        }
    )
    cfg, env = resolve_effective_bundle_cfg(p, gpu=_gpu())
    assert env == "sm89-cu130-linux-x86_64"
    assert cfg["zip"] == "https://example.com/sm89.zip"
    assert catalog_variant_keys(p) == ["sm89-cu130-linux-x86_64"]


def test_catalog_variant_missing_raises():
    p = _preset(
        {
            "bundle": {
                "variants": {
                    "sm89-cu130-linux-x86_64": {"zip": "a.zip"},
                }
            }
        }
    )
    with pytest.raises(BundleVariantNotFoundError) as exc:
        resolve_effective_bundle_cfg(p, gpu=_gpu(sm="120", cuda="128"))
    assert "sm120-cu128-linux-x86_64" in str(exc.value)
    assert "sm89-cu130-linux-x86_64" in str(exc.value)


def test_variant_dir_name():
    assert variant_dir_name(_gpu()) == "sm89-cu130-linux-x86_64"


def test_catalog_variant_alias():
    url = "https://example.com/shared.zip"
    p = _preset(
        {
            "bundle": {
                "variants": {
                    "sm89-cu130-linux-x86_64": {"zip": url},
                    "sm120-cu128-linux-x86_64": "sm89-cu130-linux-x86_64",
                }
            }
        }
    )
    cfg, env = resolve_effective_bundle_cfg(p, gpu=_gpu(sm="120", cuda="128"))
    assert env == "sm120-cu128-linux-x86_64"
    assert cfg["zip"] == url
