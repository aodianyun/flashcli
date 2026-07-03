"""GROOT N1.7 bundle script-mode manifest and argv parsing."""

from __future__ import annotations

from pathlib import Path

from flashcli_bundle.infer.cli import parse_run_argv, validate_bundle_options
from flashcli_bundle.manifest import load_bundle_manifest
from flashcli_bundle.options import bundle_run_options
from flashcli_bundle.preset import Preset

ROOT = Path(__file__).resolve().parents[1]
GROOT_N17_ROOT = ROOT / "bundles" / "groot_n17"


def test_groot_n17_default_manifest_is_script_mode() -> None:
    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    assert manifest.entry_run is not None
    assert manifest.entry_run.mode == "script"
    assert manifest.entry_run.attr == "main"
    assert manifest.name == "groot_n17"


def test_groot_n17_manifest_default_embodiment_and_views() -> None:
    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    opts = {o.name: o for o in bundle_run_options(manifest)}
    assert opts["embodiment_tag"].default == "oxe_droid_relative_eef_relative_joint"
    assert opts["num_views"].default == 2
    assert opts["config"].default == "groot_n17"
    assert opts["action_horizon"].default == 40


def test_groot_n17_manifest_declares_cosmos_backbone_extra_weights() -> None:
    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    extra = manifest.raw.get("extra_weights") or {}
    spec = extra.get("cosmos_backbone")
    assert isinstance(spec, dict)
    assert spec.get("source") == "modelscope"
    assert spec.get("repo") == "nv-community/Cosmos-Reason2-2B"
    assert spec.get("checkpoint_subdir") == "backbone"
    assert "config.json" in (spec.get("allow_patterns") or [])
    assert "model.safetensors" not in (spec.get("allow_patterns") or [])


def test_groot_n17_script_run_has_no_flashcli_bundle_import() -> None:
    text = (GROOT_N17_ROOT / "run.py").read_text(encoding="utf-8")
    assert "from flashcli_bundle" not in text
    assert "import flashcli_bundle" not in text
    assert "def main(" in text


def test_groot_n17_script_parse_passes_flags(monkeypatch) -> None:
    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    preset = Preset(
        name="groot_n17",
        raw={"description": "test", "bundle": {"local_root": str(GROOT_N17_ROOT)}},
    )
    monkeypatch.setattr(
        "flashcli_bundle.infer.cli.resolve_manifest_for_preset",
        lambda _p, bundle_path=None: manifest,
    )
    inv = parse_run_argv(
        [
            "groot_n17",
            "--prompt",
            "wave hello",
            "--embodiment-tag",
            "oxe_droid_relative_eef_relative_joint",
            "--num-views",
            "2",
            "--action-horizon",
            "40",
            "--image",
            "/tmp/a.jpg,/tmp/b.jpg",
        ],
        preset=preset,
        bundle_path=GROOT_N17_ROOT,
    )
    assert inv.entry_mode == "script"
    assert inv.bundle_argv == [
        "--prompt",
        "wave hello",
        "--embodiment-tag",
        "oxe_droid_relative_eef_relative_joint",
        "--num-views",
        "2",
        "--action-horizon",
        "40",
        "--image",
        "/tmp/a.jpg,/tmp/b.jpg",
    ]


def test_groot_n17_validate_bundle_options() -> None:
    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    assert validate_bundle_options(manifest) == []


def test_groot_n17_manifest_python_abi_is_310_for_gr00t() -> None:
    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    assert manifest.raw.get("python_abi") == "310"


def test_groot_n17_manifest_uses_vendored_gr00t_not_pip() -> None:
    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    pip = manifest.raw.get("python_dependencies", {}).get("pip", [])
    joined = " ".join(str(p) for p in pip)
    assert "gr00t @ git+" not in joined
    torch_pkg = manifest.raw.get("python_dependencies", {}).get("torch", {})
    assert torch_pkg.get("package") == "torch==2.7.1"


def test_groot_n17_runtime_sm120_py310_only() -> None:
    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    runtime = manifest.raw.get("runtime") or {}
    assert list(runtime.keys()) == ["sm120-cu130-linux-x86_64-py310"]
