"""Go host native-abi conformance: open + ABI prefix probe on the fixture.

Compiles the abi_echo stub into a temp copy of the fixture bundle, then runs
``flashcli run`` and checks the reported abi_version / struct_size
(docs/bundle_execution_abi.md section 7). Skipped without a C compiler + FlashRT
headers.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ENV_KEY = "sm89-cu124-linux-x86_64-py310"
DEFAULT_INCLUDES = ["/app/FlashRT/runtime/include", "/app/FlashRT/exec/include"]


def _compiler() -> str | None:
    return shutil.which("cc") or shutil.which("gcc")


def _include_dirs() -> list[str]:
    raw = os.environ.get("FLASHRT_INCLUDE_DIRS")
    dirs = raw.split(":") if raw else DEFAULT_INCLUDES
    return [d for d in dirs if d]


def test_go_native_abi_open(go_binary: Path, tmp_path: Path) -> None:
    cc = _compiler()
    if cc is None:
        return
    dirs = _include_dirs()
    if not (Path(dirs[0]) / "flashrt" / "model_runtime.h").is_file():
        return

    bundle = tmp_path / "abi_echo"
    shutil.copytree(FIXTURES / "abi_echo", bundle)
    runtime_dir = bundle / "runtime" / ENV_KEY
    runtime_dir.mkdir(parents=True, exist_ok=True)
    so = runtime_dir / "libabi_echo.so"
    src = bundle / "src" / "abi_echo.c"
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(so), str(src), *[f"-I{d}" for d in dirs]], check=True)

    env = dict(
        os.environ,
        FLASHCLI_SKIP_WEIGHTS="1",
        FLASHCLI_SKIP_PREFLIGHT="1",
        FLASHCLI_SKIP_VENV_SETUP="1",
        FLASHCLI_MODELS_DIR=str(tmp_path / "models"),
    )
    proc = subprocess.run(
        [str(go_binary), "run", str(bundle)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["kind"] == "native-abi"
    assert out["abi_version"] == 1
    assert out["struct_size"] >= 128
