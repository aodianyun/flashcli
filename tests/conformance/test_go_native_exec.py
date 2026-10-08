"""Go host native-exec conformance: run drives the NDJSON exec fixture.

Exercises docs/bundle_execution_abi.md section 6 end-to-end: the Go host spawns
the bundle's `native-exec` process, waits for readiness, sends a run request,
prints the response, then shuts it down.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_go_native_exec_run(go_binary: Path, tmp_path: Path) -> None:
    env = dict(
        os.environ,
        FLASHCLI_MODELS_DIR=str(tmp_path / "models"),
        FLASHCLI_SKIP_WEIGHTS="1",
        FLASHCLI_SKIP_PREFLIGHT="1",
    )
    proc = subprocess.run(
        [str(go_binary), "run", str(FIXTURES / "exec_echo"), "--prompt", "hello"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["echo"] == "hello"


def test_go_native_exec_serve_stdio_unsupported(go_binary: Path, tmp_path: Path) -> None:
    entry = FIXTURES / "exec_echo"
    if not entry.is_dir():
        return
    env = dict(
        os.environ,
        FLASHCLI_MODELS_DIR=str(tmp_path / "models"),
        FLASHCLI_SKIP_WEIGHTS="1",
        FLASHCLI_SKIP_PREFLIGHT="1",
    )
    proc = subprocess.run(
        [str(go_binary), "serve", str(entry)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "serve" in proc.stderr
