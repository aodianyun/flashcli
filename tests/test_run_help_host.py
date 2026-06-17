"""Host-side manifest-only help for run/serve (no infer re-exec)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from flashcli.cli import app
from flashcli.models.registry import Preset


def test_format_command_help_from_local_manifest(tmp_path: Path) -> None:
    from flashcli.bundle.run_help import format_command_help

    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    (bundle_root / "flashcli-bundle.json").write_text(
        """{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "protocol_version": 1,
  "name": "pi05_libero",
  "description": "Pi0.5 test bundle",
  "python_abi": "312",
  "entry": {"run": {"module": "run", "attr": "RunEngine"}},
  "run_options": [
    {"name": "prompt", "type": "string", "default": "pick", "help": "Task prompt.", "phase": "predict"}
  ]
}""",
        encoding="utf-8",
    )
    preset = Preset(
        name="pi05_libero",
        raw={"description": "test", "bundle": {"local_root": str(bundle_root)}},
        cache_key="pi05_libero/1.0.3",
    )
    text = format_command_help(preset, bundle_root, command="run")
    assert "Bundle run options:" in text
    assert "--prompt" in text
    assert "Pi0.5 test bundle" in text


def test_run_help_skips_reexec(monkeypatch: pytest.MonkeyPatch) -> None:
    reexec_called: list[str] = []
    weights_called: list[str] = []

    monkeypatch.setattr(
        "sys.argv",
        ["flashcli", "run", "flashcli-bundle/pi05_libero:1.0.3", "--help"],
    )
    monkeypatch.setattr(
        "flashcli.runtime.reexec.ensure_bundle_runtime_and_reexec",
        lambda *a, **k: reexec_called.append("yes"),
    )
    monkeypatch.setattr(
        "flashcli.cli._ensure_host_weights_before_reexec",
        lambda *a, **k: weights_called.append("yes"),
    )
    monkeypatch.setattr(
        "flashcli.bundle.run_help.resolve_manifest_for_preset",
        lambda preset, **kw: __import__(
            "flashcli.bundle.manifest", fromlist=["load_bundle_manifest"]
        ).load_bundle_manifest(
            Path(__file__).resolve().parents[1] / "bundles" / "pi05_libero"
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", "flashcli-bundle/pi05_libero:1.0.3", "--help"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Bundle run options:" in (result.stdout or result.output)
    assert not reexec_called
    assert not weights_called


def test_run_help_does_not_import_infer() -> None:
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "src" / "flashcli" / "bundle" / "run_help.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "flashcli_bundle.infer"
                assert not alias.name.startswith("flashcli_bundle.infer.")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod != "flashcli_bundle.infer"
            assert not mod.startswith("flashcli_bundle.infer.")
