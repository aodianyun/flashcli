"""GROOT N1.6 bundle script-mode manifest and argv parsing."""

from __future__ import annotations

from pathlib import Path

from flashcli_bundle.infer.cli import parse_run_argv
from flashcli_bundle.manifest import load_bundle_manifest
from flashcli_bundle.options import bundle_run_options
from flashcli_bundle.preset import Preset

ROOT = Path(__file__).resolve().parents[1]
GROOT_ROOT = ROOT / "bundles" / "groot_n16"


def test_groot_default_manifest_is_script_mode() -> None:
    manifest = load_bundle_manifest(GROOT_ROOT)
    assert manifest.entry_run is not None
    assert manifest.entry_run.mode == "script"
    assert manifest.entry_run.attr == "main"
    assert manifest.name == "groot_n16"


def test_groot_manifest_default_embodiment_and_views() -> None:
    manifest = load_bundle_manifest(GROOT_ROOT)
    opts = {o.name: o for o in bundle_run_options(manifest)}
    assert opts["embodiment_tag"].default == "gr1"
    assert opts["num_views"].default == 1
    assert opts["config"].default == "groot"
    assert opts["action_horizon"].default == 16


def test_groot_script_run_has_no_flashcli_bundle_import() -> None:
    text = (GROOT_ROOT / "run.py").read_text(encoding="utf-8")
    assert "from flashcli_bundle" not in text
    assert "import flashcli_bundle" not in text
    assert "def main(" in text


def test_groot_script_parse_passes_flags(monkeypatch) -> None:
    manifest = load_bundle_manifest(GROOT_ROOT)
    preset = Preset(
        name="groot_n16",
        raw={"description": "test", "bundle": {"local_root": str(GROOT_ROOT)}},
    )
    monkeypatch.setattr(
        "flashcli_bundle.infer.cli.resolve_manifest_for_preset",
        lambda _p, bundle_path=None: manifest,
    )
    inv = parse_run_argv(
        [
            "groot_n16",
            "--prompt",
            "wave hello",
            "--embodiment-tag",
            "gr1",
            "--num-views",
            "1",
            "--action-horizon",
            "16",
            "--image",
            "/tmp/a.jpg",
        ],
        preset=preset,
        bundle_path=GROOT_ROOT,
    )
    assert inv.entry_mode == "script"
    assert inv.bundle_argv == [
        "--prompt",
        "wave hello",
        "--embodiment-tag",
        "gr1",
        "--num-views",
        "1",
        "--action-horizon",
        "16",
        "--image",
        "/tmp/a.jpg",
    ]


def test_groot_runtime_sm120_only() -> None:
    manifest = load_bundle_manifest(GROOT_ROOT)
    runtime = manifest.raw.get("runtime") or {}
    assert list(runtime.keys()) == ["sm120-cu130-linux-x86_64-py312"]
