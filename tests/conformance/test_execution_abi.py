"""Conformance suite for the language-agnostic bundle execution ABI.

Pins docs/bundle_execution_abi.md. Every host implementation (Python today,
Go during the migration) must satisfy this same matrix so the two hosts cannot
drift. The python fixture is validated structurally; the native fixtures carry
portable reference stubs that exercise the wire protocol / factory symbol.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from flashcli_bundle.manifest import (
    load_bundle_manifest_data,
    validate_bundle_execution,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_MANIFEST_CASES = [
    ("python_echo", "run", "python"),
    ("exec_echo", "run", "native-exec"),
    ("abi_echo", "run", "native-abi"),
]


def _load(fixture: str):
    root = FIXTURES / fixture
    data = json.loads((root / "flashcli-bundle.json").read_text(encoding="utf-8"))
    return load_bundle_manifest_data(data, bundle_root=root)


@pytest.mark.parametrize("fixture,capability,kind", _MANIFEST_CASES)
def test_fixture_kind_resolves(fixture: str, capability: str, kind: str) -> None:
    manifest = _load(fixture)
    spec = manifest.entry_run if capability == "run" else manifest.entry_serve
    assert spec is not None
    assert spec.kind == kind
    assert manifest.supports(capability)
    assert validate_bundle_execution(manifest) == []


def test_python_fixture_entry_fields() -> None:
    manifest = _load("python_echo")
    assert manifest.entry_run.module == "run"
    assert manifest.entry_run.attr == "RunEngine"
    assert manifest.entry_run.native == {}


def test_exec_fixture_command_and_transport() -> None:
    manifest = _load("exec_echo")
    assert manifest.entry_run.native["command"] == ["bin/exec_echo"]
    assert manifest.entry_run.native["transport"] == "stdio"


def test_abi_fixture_library() -> None:
    manifest = _load("abi_echo")
    assert manifest.entry_run.native["library"].endswith("libabi_echo.so")
    assert manifest.entry_run.native["open_symbol"] == "frt_model_runtime_open_v1"


# --- negative matrix: every host must fail closed -------------------------


def _manifest(entry: dict, extra: dict | None = None) -> dict:
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


def test_unknown_kind_is_rejected() -> None:
    manifest = load_bundle_manifest_data(
        _manifest({"run": {"kind": "wasm"}}), bundle_root=Path("/tmp")
    )
    errors = validate_bundle_execution(manifest)
    assert any("kind" in e for e in errors)


def test_native_exec_requires_version() -> None:
    with pytest.raises(ValueError, match="exec_protocol_version"):
        load_bundle_manifest_data(
            _manifest({"run": {"kind": "native-exec", "native": {"command": ["x"]}}}),
            bundle_root=Path("/tmp"),
        )


def test_native_exec_missing_command_is_invalid() -> None:
    manifest = load_bundle_manifest_data(
        _manifest(
            {"run": {"kind": "native-exec", "native": {}}},
            {"exec_protocol_version": 1},
        ),
        bundle_root=Path("/tmp"),
    )
    assert any("command" in e for e in validate_bundle_execution(manifest))


def test_native_abi_requires_version() -> None:
    with pytest.raises(ValueError, match="runtime_abi_version"):
        load_bundle_manifest_data(
            _manifest(
                {"run": {"kind": "native-abi", "native": {"library": "lib.so"}}}
            ),
            bundle_root=Path("/tmp"),
        )


def test_stray_native_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="no native-exec entry"):
        load_bundle_manifest_data(
            _manifest({"run": {"module": "run", "attr": "RunEngine"}},
                      {"exec_protocol_version": 1}),
            bundle_root=Path("/tmp"),
        )


# --- exec_echo: real NDJSON round trip ------------------------------------


def test_exec_echo_ndjson_roundtrip() -> None:
    exe = FIXTURES / "exec_echo" / "bin" / "exec_echo"
    env = dict(os.environ, FLASHCLI_CHECKPOINT="/tmp/ckpt", FLASHCLI_BUNDLE_ROOT=str(exe.parents[1]))
    proc = subprocess.Popen(
        [str(exe)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        ready = json.loads(proc.stdout.readline())
        assert ready["op"] == "ready"
        assert ready["payload"]["checkpoint"] == "/tmp/ckpt"

        proc.stdin.write(json.dumps({"v": 1, "id": 1, "op": "run", "payload": {"prompt": "hello"}}) + "\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        assert resp == {"v": 1, "id": 1, "ok": True, "payload": {"echo": "hello"}}

        proc.stdin.write(json.dumps({"v": 1, "id": 2, "op": "shutdown", "payload": {}}) + "\n")
        proc.stdin.flush()
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


# --- abi_echo: real dlopen + prefix probe ---------------------------------


def test_abi_echo_dlopen_prefix() -> None:
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")
    default_dirs = [
        "/app/FlashRT/runtime/include",
        "/app/FlashRT/exec/include",
    ]
    dirs = os.environ.get("FLASHRT_INCLUDE_DIRS", ":".join(default_dirs)).split(":")
    header = next(
        (Path(d) / "flashrt" / "model_runtime.h" for d in dirs if d and (Path(d) / "flashrt" / "model_runtime.h").is_file()),
        None,
    )
    if header is None:
        pytest.skip("FlashRT headers not available (set FLASHRT_INCLUDE_DIRS)")

    src = FIXTURES / "abi_echo" / "src" / "abi_echo.c"
    so = FIXTURES / "abi_echo" / "src" / "libabi_echo.so"
    include_args = [f"-I{d}" for d in dirs if d]
    subprocess.run(
        [cc, "-shared", "-fPIC", "-o", str(so), str(src), *include_args],
        check=True,
        capture_output=True,
    )
    try:
        lib = ctypes.CDLL(str(so))
        open_fn = lib.frt_model_runtime_open_v1
        open_fn.restype = ctypes.c_int
        open_fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]

        out = ctypes.c_void_p()
        rc = open_fn(b'{"precision":"fp16"}', ctypes.byref(out))
        assert rc == 0
        assert out.value

        prefix = (ctypes.c_uint32 * 2).from_address(out.value)
        assert prefix[0] == 1, "abi_version must be FRT_MODEL_RUNTIME_ABI_VERSION"
        assert prefix[1] >= 8, "struct_size must cover the v1 baseline prefix"

        lib.abi_echo_last_config.restype = ctypes.c_char_p
        assert lib.abi_echo_last_config() == b'{"precision":"fp16"}'
    finally:
        so.unlink(missing_ok=True)
