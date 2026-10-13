"""Go host native-exec conformance: run drives the NDJSON exec fixture.

Exercises docs/bundle_execution_abi.md section 6 end-to-end: the Go host spawns
the bundle's `native-exec` process, waits for readiness, sends a run request,
prints the response, then shuts it down.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import urllib.request
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


def test_go_native_exec_serve_http(go_binary: Path, tmp_path: Path) -> None:
    """native-exec `serve` over http: supervise + readiness + graceful stop."""
    fx = FIXTURES / "exec_echo_http"
    if not (fx / "bin" / "exec_echo_http").is_file():
        return
    env = dict(
        os.environ,
        FLASHCLI_MODELS_DIR=str(tmp_path / "models"),
        FLASHCLI_SKIP_WEIGHTS="1",
        FLASHCLI_SKIP_PREFLIGHT="1",
    )
    proc = subprocess.Popen(
        [str(go_binary), "serve", str(fx)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        endpoint = None
        deadline = time.time() + 60
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            m = re.search(r"(http://127\.0\.0\.1:\d+)", line)
            if m:
                endpoint = m.group(1)
                break
        assert endpoint, "host did not report a serve endpoint"
        with urllib.request.urlopen(endpoint + "/healthz", timeout=10) as r:
            assert json.load(r)["status"] == "ok"
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
