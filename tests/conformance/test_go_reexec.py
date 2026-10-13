"""Go host re-exec conformance: run/serve must exec the bundle infer process.

The Go host prepares the bundle venv, then ``syscall.Exec``s
``<venv>/python -m flashcli_bundle.infer <capability> ...`` with the offline /
in-bundle env (docs/bundle_execution_abi.md section 5, reexec.py). This test
uses a fake venv interpreter so it does not need torch or a real install.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9._+\-]+")


def _runtime_id(path: str, name: str) -> str:
    safe = _SAFE.sub("-", name.strip()).strip("-") or "bundle"
    digest = hashlib.sha256(path.strip().encode()).hexdigest()[:12]
    return f"{safe}-local-{digest}"


def _make_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "run.py").write_text("class RunEngine:  # pragma: no cover\n    pass\n", encoding="utf-8")
    (bundle / "flashcli-bundle.json").write_text(
        json.dumps(
            {
                "format": "flashcli-model-bundle",
                "format_version": 3,
                "protocol_version": 1,
                "name": "reexec_fixture",
                "python_abi": "310",
                "entry": {"run": {"module": "run", "attr": "RunEngine"}},
                "runtime": {"sm89-cu124-linux-x86_64-py310": "runtime/x"},
            }
        ),
        encoding="utf-8",
    )
    return bundle


def _fake_venv(runtimes: Path, runtime_id: str) -> Path:
    bin_dir = runtimes / runtime_id / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do echo "ARG:$a"; done\n'
        'echo "OFFLINE:$HF_HUB_OFFLINE"\n'
        'echo "INVENV:$FLASHCLI_IN_BUNDLE_VENV"\n'
        'echo "RUNTIME:$FLASHCLI_RUNTIME_ID"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    return python


def test_go_run_reexecs_infer(go_binary: Path, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    runtimes = tmp_path / "runtimes"
    runtime_id = _runtime_id(str(bundle.resolve()), "reexec_fixture")
    _fake_venv(runtimes, runtime_id)

    env = dict(
        os.environ,
        FLASHCLI_RUNTIMES_DIR=str(runtimes),
        FLASHCLI_SKIP_VENV_SETUP="1",
        FLASHCLI_SKIP_PREFLIGHT="1",
        FLASHCLI_SKIP_WEIGHTS="1",
    )
    proc = subprocess.run(
        [str(go_binary), "run", str(bundle), "--prompt", "hi"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "ARG:-m" in out and "ARG:flashcli_bundle.infer" in out
    assert "ARG:run" in out and "ARG:--prompt" in out and "ARG:hi" in out
    assert f"ARG:{bundle}" in out
    assert "OFFLINE:1" in out
    assert "INVENV:1" in out
    assert f"RUNTIME:{runtime_id}" in out


def test_go_run_rejects_unsupported_capability(go_binary: Path, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    runtimes = tmp_path / "runtimes"
    env = dict(
        os.environ,
        FLASHCLI_RUNTIMES_DIR=str(runtimes),
        FLASHCLI_SKIP_VENV_SETUP="1",
        FLASHCLI_SKIP_PREFLIGHT="1",
        FLASHCLI_SKIP_WEIGHTS="1",
    )
    proc = subprocess.run(
        [str(go_binary), "serve", str(bundle)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "does not support serve" in proc.stderr
