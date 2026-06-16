"""Weights are pulled on the host CLI, not inside the bundle venv."""

from __future__ import annotations

from pathlib import Path

import pytest

from flashcli.bundle.weights import ensure_checkpoint
from flashcli.models.cache import ensure_model_cached
from flashcli.models.registry import Preset


def test_ensure_checkpoint_resolve_only_raises_without_cache(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    manifest_path = bundle_root / "flashcli-bundle.json"
    manifest_path.write_text(
        """
{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "protocol_version": 1,
  "name": "test",
  "python_abi": "312",
  "weights": {"source": "huggingface", "repo": "org/model"},
  "runtime": {"sm89-cu124-linux-x86_64-py312": "runtime/x"},
  "entry": {"run": {"module": "run", "attr": "RunEngine"}}
}
""".strip(),
        encoding="utf-8",
    )
    (bundle_root / "runtime").mkdir()
    (bundle_root / "runtime" / "x").mkdir(parents=True)

    from flashcli_bundle.manifest import BundleManifest

    bundle = BundleManifest(
        bundle_root=bundle_root,
        name="test",
        capabilities=[],
        entry_run=None,
        entry_serve=None,
        raw={
            "weights": {"source": "huggingface", "repo": "org/model"},
        },
    )
    preset = Preset(
        name="test_preset",
        raw={"engine": "model_bundle", "bundle": {"path": str(bundle_root)}},
    )

    with pytest.raises(FileNotFoundError, match="flashcli pull test_preset"):
        ensure_checkpoint(preset, bundle, download=False)


def test_ensure_model_cached_rejects_download_in_bundle_venv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLASHCLI_IN_BUNDLE_VENV", "1")
    with pytest.raises(RuntimeError, match="host flashcli CLI"):
        ensure_model_cached("any_preset", download=True)
