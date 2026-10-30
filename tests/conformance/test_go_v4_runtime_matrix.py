"""Real Go-host conformance for v4 runtime selection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v4_runtime_matrix"
_SAFE = re.compile(r"[^A-Za-z0-9._+\-]+")
_RUNTIME_ENV = "sm120-cu130-linux-x86_64-py312"


def _runtime_id(path: Path, name: str) -> str:
    safe = _SAFE.sub("-", name.strip()).strip("-") or "bundle"
    digest = hashlib.sha256(str(path).encode()).hexdigest()[:12]
    return f"{safe}-local-{digest}"


def _build_runtime(bundle: Path) -> Path:
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")
    cell = bundle / "runtime" / "shared"
    cell.mkdir(parents=True)
    src = cell / "kernels.c"
    src.write_text(
        "#include <Python.h>\n"
        "static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, \"flash_rt_kernels\", NULL, -1, NULL};\n"
        "PyMODINIT_FUNC PyInit_flash_rt_kernels(void) { return PyModule_Create(&module); }\n",
        encoding="utf-8",
    )
    so = cell / f"flash_rt_kernels-v1.2.0-{_RUNTIME_ENV}.so"
    import sysconfig
    subprocess.run(
        [cc, "-shared", "-fPIC", f"-I{sysconfig.get_paths()['include']}", "-o", str(so), str(src)],
        check=True,
        capture_output=True,
    )
    src.unlink()
    return cell


def _make_real_venv(bundle: Path, runtimes: Path) -> None:
    venv = runtimes / _runtime_id(bundle, "v4_runtime_matrix") / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
        check=True,
        capture_output=True,
    )
    probe = subprocess.run(
        [str(venv / "bin" / "python"), "-c", "import flashcli_bundle"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip("flashcli_bundle is not importable in the test interpreter")


def _copy_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "v4_runtime_matrix"
    shutil.copytree(FIXTURE, bundle)
    _build_runtime(bundle)
    return bundle


def _run(go_binary: Path, bundle: Path, tmp_path: Path, *, key: str | None) -> str:
    runtimes = tmp_path / "runtimes"
    _make_real_venv(bundle, runtimes)
    env = dict(
        os.environ,
        FLASHCLI_HOME=str(tmp_path / "home"),
        FLASHCLI_RUNTIMES_DIR=str(runtimes),
        FLASHCLI_SKIP_VENV_SETUP="1",
        FLASHCLI_SKIP_WEIGHTS="1",
        FLASHCLI_SKIP_CUDA_USERLAND="1",
    )
    if key:
        env["FLASHCLI_RUNTIME_ENV_KEY"] = key
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir(exist_ok=True)
    proc = subprocess.run(
        [str(go_binary), "run", str(bundle), "--checkpoint", str(checkpoint), "--prompt", "matrix"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_v4_shared_runtime_automatic_fallback(go_binary: Path, tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    out = _run(go_binary, bundle, tmp_path, key=None)
    assert "V4_RUNTIME_MATRIX_OK" in out
    assert "shared-nvidia" in out or "shared-cpu" in out
    data = json.loads((bundle / "flashcli-bundle.json").read_text(encoding="utf-8"))
    assert data["environments"]["shared-nvidia"]["runtime"] == "runtime/shared"
    assert data["environments"]["shared-cpu"]["runtime"] == "runtime/shared"


def test_v4_runtime_less_environment(go_binary: Path, tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    out = _run(go_binary, bundle, tmp_path, key="runtime-less")
    assert "V4_RUNTIME_MATRIX_OK runtime-less" in out
