"""Pi05 bundle script-mode manifest and argv parsing."""

from __future__ import annotations

import json
from pathlib import Path

from flashcli_bundle.infer.cli import parse_run_argv
from flashcli_bundle.manifest import load_bundle_manifest
from flashcli_bundle.preset import Preset

ROOT = Path(__file__).resolve().parents[1]
PI05_ROOT = ROOT / "bundles" / "pi05_libero"


def test_pi05_default_manifest_is_script_mode() -> None:
    manifest = load_bundle_manifest(PI05_ROOT)
    assert manifest.entry_run is not None
    assert manifest.entry_run.mode == "script"
    assert manifest.entry_run.attr == "main"


def test_pi05_engine_manifest_example() -> None:
    data = json.loads((PI05_ROOT / "flashcli-bundle.engine.json").read_text(encoding="utf-8"))
    from flashcli_bundle.manifest import load_bundle_manifest_data

    engine = load_bundle_manifest_data(data, bundle_root=PI05_ROOT)
    assert engine.entry_run is not None
    assert engine.entry_run.mode == "engine"
    assert engine.entry_run.attr == "RunEngine"
    assert engine.entry_run.module == "run_engine"


def test_pi05_script_run_has_no_flashcli_bundle_import() -> None:
    text = (PI05_ROOT / "run.py").read_text(encoding="utf-8")
    assert "from flashcli_bundle" not in text
    assert "import flashcli_bundle" not in text
    assert "def main(" in text


def test_pi05_engine_module_imports_flashcli_bundle() -> None:
    text = (PI05_ROOT / "run_engine.py").read_text(encoding="utf-8")
    assert "flashcli_bundle" in text
    assert "class RunEngine" in text


def test_pi05_script_parse_passes_flags(monkeypatch) -> None:
    manifest = load_bundle_manifest(PI05_ROOT)
    preset = Preset(
        name="pi05_libero",
        raw={"description": "test", "bundle": {"local_root": str(PI05_ROOT)}},
    )
    monkeypatch.setattr(
        "flashcli_bundle.infer.cli.resolve_manifest_for_preset",
        lambda _p, bundle_path=None: manifest,
    )
    inv = parse_run_argv(
        [
            "pi05_libero",
            "--prompt",
            "grasp cup",
            "--num-views",
            "2",
            "--image",
            "/tmp/a.jpg,/tmp/b.jpg",
        ],
        preset=preset,
        bundle_path=PI05_ROOT,
    )
    assert inv.entry_mode == "script"
    assert inv.bundle_argv == [
        "--prompt",
        "grasp cup",
        "--num-views",
        "2",
        "--image",
        "/tmp/a.jpg,/tmp/b.jpg",
    ]


def test_pi05_script_parse_passes_benchmark_flags(monkeypatch) -> None:
    manifest = load_bundle_manifest(PI05_ROOT)
    preset = Preset(
        name="pi05_libero",
        raw={"description": "test", "bundle": {"local_root": str(PI05_ROOT)}},
    )
    monkeypatch.setattr(
        "flashcli_bundle.infer.cli.resolve_manifest_for_preset",
        lambda _p, bundle_path=None: manifest,
    )
    inv = parse_run_argv(
        ["pi05_libero", "--benchmark", "5", "--warmup", "2"],
        preset=preset,
        bundle_path=PI05_ROOT,
    )
    assert inv.entry_mode == "script"
    assert inv.bundle_argv == ["--benchmark", "5", "--warmup", "2"]
