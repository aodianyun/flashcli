"""Tests for bundle runtime cache / resync decisions."""

from __future__ import annotations

import json
from pathlib import Path

from flashcli.bundle.artifacts import _runtime_is_ready


def _write_bundle_root(root: Path, *, manifest: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "flashcli-bundle.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (root / "run.py").write_text("# stub\n", encoding="utf-8")
    (root / "flash_rt").mkdir()
    native = root / "runtime/sm89-cu130-linux-x86_64-py312"
    native.mkdir(parents=True)
    (native / "flash_rt_kernels-sm89-cu130-linux-x86_64-py312.so").write_bytes(b"so")


def test_runtime_not_ready_when_manifest_differs(tmp_path: Path) -> None:
    repo = "https://flashhub.example/pi05/1.0.3"
    manifest_v2 = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "pi05_libero",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "runtime": {"sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312"},
    }
    manifest_v1 = dict(manifest_v2)
    manifest_v1.pop("protocol_version")

    bundle_root = tmp_path / "root"
    staging = tmp_path / "staging-manifest.json"
    _write_bundle_root(bundle_root, manifest=manifest_v1)
    staging.write_text(json.dumps(manifest_v2, indent=2) + "\n", encoding="utf-8")

    marker = {
        "repo_url": repo,
        "env_key": "sm89-cu130-linux-x86_64-py312",
    }
    assert not _runtime_is_ready(
        bundle_root=bundle_root,
        manifest_cache=staging,
        marker=marker,
        repo_url=repo,
        env_key="sm89-cu130-linux-x86_64-py312",
        artifact_rel="runtime/sm89-cu130-linux-x86_64-py312",
        force=False,
    )


def test_runtime_ready_when_manifest_matches(tmp_path: Path) -> None:
    repo = "https://flashhub.example/pi05/1.0.3"
    manifest = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "pi05_libero",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "runtime": {"sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312"},
    }
    bundle_root = tmp_path / "root"
    staging = tmp_path / "staging-manifest.json"
    _write_bundle_root(bundle_root, manifest=manifest)
    staging.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    marker = {
        "repo_url": repo,
        "env_key": "sm89-cu130-linux-x86_64-py312",
    }
    assert _runtime_is_ready(
        bundle_root=bundle_root,
        manifest_cache=staging,
        marker=marker,
        repo_url=repo,
        env_key="sm89-cu130-linux-x86_64-py312",
        artifact_rel="runtime/sm89-cu130-linux-x86_64-py312",
        force=False,
    )


def test_runtime_not_ready_when_repo_url_changes(tmp_path: Path) -> None:
    manifest = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "pi05_libero",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "runtime": {"sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312"},
    }
    bundle_root = tmp_path / "root"
    staging = tmp_path / "staging-manifest.json"
    _write_bundle_root(bundle_root, manifest=manifest)
    staging.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    marker = {
        "repo_url": "https://flashhub.example/pi05/1.0.2",
        "env_key": "sm89-cu130-linux-x86_64-py312",
    }
    assert not _runtime_is_ready(
        bundle_root=bundle_root,
        manifest_cache=staging,
        marker=marker,
        repo_url="https://flashhub.example/pi05/1.0.3",
        env_key="sm89-cu130-linux-x86_64-py312",
        artifact_rel="runtime/sm89-cu130-linux-x86_64-py312",
        force=False,
    )
