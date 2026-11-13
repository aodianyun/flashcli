"""Real CLI surface: version, doctor, manifest validation, env resolution."""

from __future__ import annotations

import json
import re

from helpers import CELL, FIXTURES, prepare_bundle, run_cli


def _pyproject_version() -> str:
    text = (FIXTURES.parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match
    return match.group(1)


def test_version_matches_pyproject(flashcli_bin, cli_env):
    proc = run_cli(flashcli_bin, cli_env, "version")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _pyproject_version()


def test_doctor_runs(flashcli_bin, cli_env):
    proc = run_cli(flashcli_bin, cli_env, "doctor", timeout=120)
    out = proc.stdout + proc.stderr
    assert "[ok] flashcli-go" in out


def test_bundle_validate_all_kinds(flashcli_bin, cli_env, home):
    for fixture, kind in (
        ("python_echo", "v3 python"),
        ("v4_python_echo", "v4 python"),
        ("exec_echo", "v3 native-exec"),
    ):
        bundle = prepare_bundle(fixture, home)
        proc = run_cli(flashcli_bin, cli_env, "bundle", "validate", str(bundle), timeout=120)
        assert proc.returncode == 0, f"{kind}: {proc.stdout}\n{proc.stderr}"


def test_models_show_reports_host_and_match(flashcli_bin, cli_env, home):
    bundle = prepare_bundle("v4_python_echo", home)
    proc = run_cli(flashcli_bin, cli_env, "models", "show", str(bundle), timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "this machine:" in out
    assert CELL in out
    assert "supported (1)" in out


def test_bundle_validate_rejects_broken_manifest(flashcli_bin, cli_env, tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "flashcli-bundle.json").write_text(json.dumps({"format": "x"}), encoding="utf-8")
    proc = run_cli(flashcli_bin, cli_env, "bundle", "validate", str(broken), timeout=60)
    assert proc.returncode != 0
    assert "format" in (proc.stdout + proc.stderr).lower()
