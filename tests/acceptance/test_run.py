"""Real ``flashcli run`` on v3/v4 python bundles and a native bundle.

The host creates the bundle venv, re-execs the infer entry (or spawns the native
process), and prints the entry result as JSON. Nothing is mocked.
"""

from __future__ import annotations

import json
import os

import pytest

from helpers import prepare_bundle, run_cli

_HEAVY = pytest.mark.skipif(
    os.environ.get("FLASHCLI_ACCEPTANCE_HEAVY") != "1",
    reason="heavy tier: installs the torch stack; set FLASHCLI_ACCEPTANCE_HEAVY=1",
)


@_HEAVY
@pytest.mark.parametrize("fixture", ["python_echo", "v4_python_echo"])
def test_run_python_bundle(flashcli_bin, cli_env, home, fixture):
    bundle = prepare_bundle(fixture, home)
    proc = run_cli(flashcli_bin, cli_env, "run", str(bundle), "--prompt", "hello", timeout=900)
    assert proc.returncode == 0, proc.stderr[-4000:]
    out = proc.stdout
    # The python backend reports completion (the entry result is not always JSON).
    assert "Done. result type=dict" in out
    assert "Using bundle-local weights" in out


def test_run_native_exec_bundle(flashcli_bin, cli_env, home):
    bundle = prepare_bundle("exec_echo", home)
    proc = run_cli(flashcli_bin, cli_env, "run", str(bundle), "--prompt", "hello", timeout=300)
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert json.loads(proc.stdout)["echo"] == "hello"
