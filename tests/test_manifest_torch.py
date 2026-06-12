"""Tests for manifest torch index and native matrix helpers."""

from __future__ import annotations

from pathlib import Path

from flashcli.bundle.manifest import (
    bundle_runtime_matrix,
    bundle_torch_index,
    load_bundle_manifest_data,
)
from flashcli.runtime.requirements_spec import parse_torch_dependency


def test_parse_torch_dependency_object() -> None:
    pkg, idx = parse_torch_dependency({"package": "torch", "index": "cu128"})
    assert pkg == "torch"
    assert idx == "cu128"


def test_parse_torch_dependency_string() -> None:
    pkg, idx = parse_torch_dependency("torch")
    assert pkg == "torch"
    assert idx == ""


def test_bundle_torch_index_auto_from_env_key(tmp_path: Path) -> None:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "name": "t",
        "python_abi": "312",
        "python_dependencies": {
            "torch": {"package": "torch", "index": "auto"},
            "pip": [],
        },
        "runtime": {
            "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
        },
    }
    manifest = load_bundle_manifest_data(data, bundle_root=tmp_path)
    assert bundle_torch_index(manifest, env_key="sm89-cu124-linux-x86_64-py312") == "cu124"
    assert bundle_torch_index(manifest, env_key="sm120-cu130-linux-x86_64-py312") == "cu128"


def test_bundle_torch_index_from_python_dependencies(tmp_path: Path) -> None:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "name": "t",
        "python_abi": "312",
        "python_dependencies": {
            "torch": {"package": "torch", "index": "cu130"},
            "pip": [],
        },
        "runtime": {
            "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
        },
    }
    manifest = load_bundle_manifest_data(data, bundle_root=tmp_path)
    assert bundle_torch_index(manifest) == "cu130"


def test_bundle_runtime_matrix_from_runtime_map(tmp_path: Path) -> None:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "name": "t",
        "python_abi": "312",
        "python_dependencies": {"torch": "torch", "pip": []},
        "runtime": {
            "sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312",
            "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
        },
    }
    manifest = load_bundle_manifest_data(data, bundle_root=tmp_path)
    assert bundle_runtime_matrix(manifest) == [
        "sm89-cu124-linux-x86_64-py312",
        "sm89-cu130-linux-x86_64-py312",
    ]
