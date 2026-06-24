"""Tests for manifest entry ``mode: script`` (pass-through argv)."""

from __future__ import annotations

from pathlib import Path

import pytest

from flashcli.bundle.manifest import load_bundle_manifest_data
from flashcli.bundle.run_argv import peel_host_run_flags, peel_script_host_flags
from flashcli.models.registry import Preset
from flashcli_bundle.help_text import format_run_help
from flashcli_bundle.infer.cli import parse_run_argv
from flashcli_bundle.manifest import EntrySpec, entry_mode_for_capability
from flashcli_bundle.manifest_ext import validate_bundle_layout
from flashcli_bundle.options import bundle_run_options_for_help


def _script_manifest(tmp_path: Path, *, mode: str = "script"):
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "script_demo",
        "description": "Script entry demo",
        "python_abi": "312",
        "entry": {
            "run": {"module": "run", "attr": "main", "mode": mode},
        },
        "run_options": [
            {
                "name": "prompt",
                "type": "string",
                "default": "hello",
                "help": "Task prompt.",
                "phase": "predict",
            },
        ],
        "runtime": {
            "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
        },
    }
    return load_bundle_manifest_data(data, bundle_root=tmp_path)


def test_entry_spec_parses_mode() -> None:
    spec = EntrySpec.from_dict({"module": "run", "attr": "main", "mode": "script"})
    assert spec is not None
    assert spec.mode == "script"

    default = EntrySpec.from_dict({"module": "run", "attr": "RunEngine"})
    assert default is not None
    assert default.mode == "engine"


def test_entry_spec_invalid_mode_defaults_engine() -> None:
    spec = EntrySpec.from_dict({"module": "run", "attr": "main", "mode": "bogus"})
    assert spec is not None
    assert spec.mode == "engine"


def test_validate_layout_rejects_invalid_entry_mode(tmp_path: Path) -> None:
    manifest = _script_manifest(tmp_path, mode="custom")
    errors = validate_bundle_layout(manifest)
    assert any("entry.run.mode" in e for e in errors)


def test_entry_mode_for_capability(tmp_path: Path) -> None:
    manifest = _script_manifest(tmp_path)
    assert entry_mode_for_capability(manifest, "run") == "script"
    assert entry_mode_for_capability(manifest, "serve") == "engine"


def test_parse_run_argv_script_passes_unknown_flags(tmp_path: Path, monkeypatch) -> None:
    manifest = _script_manifest(tmp_path)
    preset = Preset(
        name="script_demo",
        raw={"description": "test", "bundle": {"local_root": str(tmp_path)}},
    )
    monkeypatch.setattr(
        "flashcli_bundle.infer.cli.resolve_manifest_for_preset",
        lambda _p, bundle_path=None: manifest,
    )
    inv = parse_run_argv(
        [
            "script_demo",
            "--prompt",
            "move cup",
            "--quiet",
            "--unknown-flag",
            "value",
        ],
        preset=preset,
        bundle_path=tmp_path,
    )
    assert inv.entry_mode == "script"
    assert inv.bundle_argv == [
        "--prompt",
        "move cup",
        "--quiet",
        "--unknown-flag",
        "value",
    ]
    assert inv.quiet is False
    assert inv.bundle_options is None


def test_format_run_help_script_mode_note(tmp_path: Path) -> None:
    manifest = _script_manifest(tmp_path)
    preset = Preset(name="script_demo", raw={"description": "catalog desc"})
    text = format_run_help(
        preset,
        manifest,
        bundle_run_options_for_help(manifest),
        entry_mode="script",
    )
    assert "[OPTIONS...]" in text
    assert "documentation only" in text
    assert "--prompt" in text
    assert "--benchmark" not in text


def test_peel_script_host_flags_only_checkpoint() -> None:
    flags = peel_script_host_flags(
        ["run", "demo/ref", "--checkpoint", "/ckpt", "--quiet", "--prompt", "x"],
        command="run",
    )
    assert flags.checkpoint == Path("/ckpt")
    assert flags.wants_help is False

    engine_flags = peel_host_run_flags(
        ["run", "demo/ref", "--checkpoint", "/ckpt", "--quiet"],
        command="run",
    )
    assert engine_flags.quiet is True
    assert engine_flags.checkpoint == Path("/ckpt")


def test_execute_run_script_invokes_main(tmp_path: Path, monkeypatch) -> None:
    from flashcli_bundle.infer.app import execute_run
    from flashcli_bundle.preset import Preset as BundlePreset

    manifest = _script_manifest(tmp_path)
    preset = BundlePreset(
        name="script_demo",
        raw={"engine": "model_bundle", "bundle": {"local_root": str(tmp_path)}},
    )
    captured: dict[str, list[str]] = {}

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = list(argv)
        return 42

    mock_bundle = manifest

    monkeypatch.setattr(
        "flashcli_bundle.infer.bundle.resolve.activate_for_preset",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "flashcli_bundle.infer.bundle.activate.active_bundle",
        lambda: mock_bundle,
    )
    monkeypatch.setattr(
        "flashcli_bundle.infer.app.model_cache.ensure_model_cached",
        lambda *a, **k: tmp_path / "ckpt",
    )
    monkeypatch.setattr(
        "flashcli_bundle.infer.engines.entry_invoke.load_entry_callable",
        lambda spec, kind: fake_main,
    )

    import typer

    with pytest.raises(typer.Exit) as exc:
        execute_run(
            preset,
            bundle=tmp_path,
            entry_mode="script",
            bundle_argv=["--prompt", "x", "--quiet"],
        )
    assert exc.value.exit_code == 42
    assert captured["argv"] == ["--prompt", "x", "--quiet"]


def test_host_script_pull_uses_checkpoint_only(tmp_path: Path, monkeypatch) -> None:
    from flashcli.models.registry import Preset as HostPreset

    manifest = _script_manifest(tmp_path)
    preset = HostPreset(name="script_demo", raw={"engine": "model_bundle"})
    ensure_calls: list[dict] = []

    monkeypatch.setattr(
        "flashcli.bundle.preset_validate.fetch_manifest_for_preset",
        lambda *a, **k: manifest,
    )
    monkeypatch.setattr(
        "flashcli.bundle.run_argv.resolve_run_from_argv",
        lambda *a, **k: (preset, tmp_path),
    )
    monkeypatch.setattr("flashcli.cli._auto_install_flag", lambda _: False)
    monkeypatch.setattr("flashcli.cli.ensure_environment", lambda **k: None)
    monkeypatch.setattr(
        "flashcli.bundle.preset_validate.validate_preset_before_sync",
        lambda *a, **k: manifest,
    )
    monkeypatch.setattr(
        "flashcli.runtime.reexec.prepare_bundle_runtime",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "flashcli.models.cache.ensure_model_cached",
        lambda *a, **k: ensure_calls.append(
            {
                "checkpoint_override": k.get("checkpoint_override"),
                "download": k.get("download"),
            }
        )
        or tmp_path,
    )
    monkeypatch.setattr(
        "flashcli.runtime.reexec.ensure_bundle_runtime_and_reexec",
        lambda *a, **k: (_ for _ in ()).throw(SystemExit(0)),
    )

    import flashcli.cli as cli_mod

    monkeypatch.setattr(
        "sys.argv",
        ["flashcli", "run", "script_demo", "--checkpoint", str(tmp_path / "local")],
    )

    with pytest.raises(SystemExit):
        cli_mod.run()

    assert len(ensure_calls) == 1
    assert ensure_calls[0]["checkpoint_override"] == tmp_path / "local"
    assert ensure_calls[0]["download"] is True
