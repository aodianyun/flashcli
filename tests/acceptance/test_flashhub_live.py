"""Live FlashHub acceptance (network tier): real API + manifest resolution.

Skipped unless ``FLASHCLI_ACCEPTANCE_NETWORK=1``. Cheap: fetches the repo index
and manifest only (``models show``), so it is safe to run before a release.
"""

from __future__ import annotations

import os

import pytest

from helpers import run_cli

pytestmark = pytest.mark.skipif(
    os.environ.get("FLASHCLI_ACCEPTANCE_NETWORK") != "1",
    reason="network tier: set FLASHCLI_ACCEPTANCE_NETWORK=1",
)

REF = os.environ.get("FLASHCLI_ACCEPTANCE_REF", "rsi-flashrt/qwen35_4b_nvfp4:1.0.1")


def test_live_manifest_resolves(flashcli_bin, cli_env, tmp_path):
    env = dict(cli_env)
    env.pop("FLASHCLI_RUNTIME_ENV_KEY", None)  # use the real host key
    env["FLASHCLI_HOME"] = str(tmp_path / "home")
    proc = run_cli(flashcli_bin, env, "models", "show", REF, timeout=180)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-4000:]
    out = proc.stdout
    assert "this machine:" in out
    assert "supported (" in out
    # The bundle must declare at least one environment for this host family.
    assert "sm" in out
