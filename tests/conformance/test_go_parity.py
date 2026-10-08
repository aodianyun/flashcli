"""Py/Go execution-ABI parity gate.

The Go host must agree with the Python host on which manifests are valid. This
test runs the Go validator against the same fixtures and negative cases as the
Python validator. Skipped when the Go toolchain or module cache is unavailable.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from flashcli_bundle.manifest import (
    load_bundle_manifest_data,
    validate_bundle_execution,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _py_execution_ok(data: dict, root: Path) -> bool:
    try:
        manifest = load_bundle_manifest_data(data, bundle_root=root)
    except ValueError:
        return False
    return validate_bundle_execution(manifest) == []


def _go_execution_ok(go_binary: Path, bundle: Path) -> bool:
    proc = subprocess.run(
        [str(go_binary), "bundle", "validate", str(bundle), "--json", "--execution-only"],
        capture_output=True,
        text=True,
    )
    result = json.loads(proc.stdout)
    return bool(result["ok"])


def _base_data(entry: dict, extra: dict | None = None) -> dict:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "t",
        "python_abi": "310",
        "entry": entry,
        "runtime": {"sm89-cu124-linux-x86_64-py310": "runtime/x"},
    }
    if extra:
        data.update(extra)
    return data


_NEGATIVE_CASES = {
    "unknown_kind": _base_data({"run": {"kind": "wasm"}}),
    "exec_missing_version": _base_data(
        {"run": {"kind": "native-exec", "native": {"command": ["x"]}}}
    ),
    "abi_missing_version": _base_data(
        {"run": {"kind": "native-abi", "native": {"library": "lib.so"}}}
    ),
    "stray_exec_version": _base_data(
        {"run": {"module": "run", "attr": "RunEngine"}}, {"exec_protocol_version": 1}
    ),
    "exec_missing_command": _base_data(
        {"run": {"kind": "native-exec", "native": {}}}, {"exec_protocol_version": 1}
    ),
}


@pytest.mark.parametrize("fixture", ["python_echo", "exec_echo", "abi_echo"])
def test_fixtures_agree(go_binary: Path, fixture: str) -> None:
    root = FIXTURES / fixture
    data = json.loads((root / "flashcli-bundle.json").read_text(encoding="utf-8"))
    assert _py_execution_ok(data, root) is True
    assert _go_execution_ok(go_binary, root) is True


@pytest.mark.parametrize("name", sorted(_NEGATIVE_CASES))
def test_negative_cases_agree(go_binary: Path, tmp_path: Path, name: str) -> None:
    data = _NEGATIVE_CASES[name]
    bundle = tmp_path / name
    bundle.mkdir()
    (bundle / "flashcli-bundle.json").write_text(json.dumps(data), encoding="utf-8")
    assert _py_execution_ok(data, bundle) is False
    assert _go_execution_ok(go_binary, bundle) is False
