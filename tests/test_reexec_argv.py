"""Tests for reexec into flashcli_bundle.infer."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.models.registry import Preset
from flashcli.runtime import reexec


def _preset() -> Preset:
    return Preset(
        name="flashcli-bundle/test:1.0.0",
        raw={"engine": "model_bundle", "bundle": {"repo": "https://example.test/x"}},
        cache_key="test/1.0.0",
    )


def test_reexec_argv_uses_flashcli_bundle_infer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_id = "test-runtime"
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    (bundle_root / "flashcli-bundle.json").write_text(
        '{"format":"flashcli-model-bundle","format_version":3,"protocol_version":1,'
        '"name":"t","python_abi":"312","entry":{"run":{"module":"run","attr":"RunEngine"}},'
        '"python_dependencies":{"torch":{"package":"torch","index":"cu124"},"pip":[]},'
        '"runtime":{"sm89-cu124-linux-x86_64-py312":"runtime/x"}}',
        encoding="utf-8",
    )
    py = tmp_path / "python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)

    monkeypatch.setattr(
        reexec,
        "prepare_bundle_runtime",
        lambda *args, **kwargs: (runtime_id, bundle_root),
    )
    monkeypatch.setattr(reexec, "in_bundle_venv", lambda _rid: False)
    monkeypatch.setattr(reexec, "venv_python", lambda _rid: py)
    monkeypatch.setattr(reexec, "ensure_flashcli_bundle_in_venv", lambda **kwargs: None)

    seen: dict[str, object] = {}

    def fake_execve(path: str, argv: list[str], env: dict[str, str]) -> None:
        seen["argv"] = argv
        seen["env"] = env
        raise SystemExit(0)

    monkeypatch.setattr(os, "execve", fake_execve)
    monkeypatch.setattr(
        "sys.argv",
        ["flashcli", "run", "flashcli-bundle/test:1.0.0", "--prompt", "hi"],
    )

    with pytest.raises(SystemExit):
        reexec.ensure_bundle_runtime_and_reexec(_preset())

    argv = seen["argv"]
    assert isinstance(argv, list)
    assert argv[1:4] == ["-m", "flashcli_bundle.infer", "run"]
    env = seen["env"]
    assert isinstance(env, dict)
    assert "PYTHONPATH" not in env or not str(env.get("PYTHONPATH", "")).strip()
