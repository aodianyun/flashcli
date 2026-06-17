"""Tests for manifest ``run_options`` / ``serve_options`` and argv parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from flashcli.bundle.bundle_options import (
    BundleOptionsError,
    bundle_run_options,
    bundle_run_options_for_help,
    bundle_serve_options,
    format_run_help,
    format_serve_help,
    parse_run_argv,
    parse_serve_argv,
    run_option_defaults,
    serve_option_defaults,
    split_run_options,
    split_serve_options,
)
from flashcli.bundle.manifest import load_bundle_manifest_data
from flashcli.models.registry import Preset


def _pi05_manifest(tmp_path: Path):
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "pi05_libero",
        "description": "Pi0.5 test",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "run_options": [
            {
                "name": "prompt",
                "type": "string",
                "default": "pick block",
                "help": "Task prompt.",
                "phase": "predict",
            },
            {
                "name": "num_views",
                "type": "integer",
                "default": 2,
                "help": "Camera views.",
                "phase": "load",
            },
        ],
        "runtime": {
            "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
        },
    }
    return load_bundle_manifest_data(data, bundle_root=tmp_path)


def test_bundle_run_options_split_by_phase(tmp_path: Path) -> None:
    manifest = _pi05_manifest(tmp_path)
    specs = bundle_run_options(manifest)
    load_kw, predict_kw = split_run_options(
        {"prompt": "hello", "num_views": 3}, specs
    )
    assert load_kw == {"num_views": 3}
    assert predict_kw == {"prompt": "hello"}


def test_parse_run_argv_bundle_flags(tmp_path: Path, monkeypatch) -> None:
    manifest = _pi05_manifest(tmp_path)
    preset = Preset(
        name="pi05_libero",
        raw={"description": "test", "bundle": {"local_root": str(tmp_path)}},
    )
    monkeypatch.setattr(
        "flashcli.bundle.bundle_options.resolve_manifest_for_preset",
        lambda _p, bundle_path=None: manifest,
    )
    inv = parse_run_argv(
        ["pi05_libero", "--prompt", "move cup", "--num-views", "2", "--quiet"],
        preset=preset,
        bundle_path=tmp_path,
    )
    assert inv.quiet is True
    assert inv.bundle_options == {"prompt": "move cup", "num_views": 2}


def test_format_run_help_lists_bundle_options(tmp_path: Path) -> None:
    manifest = _pi05_manifest(tmp_path)
    preset = Preset(name="pi05_libero", raw={"description": "catalog desc"})
    text = format_run_help(
        preset,
        manifest,
        bundle_run_options_for_help(manifest),
    )
    assert "Common options (flashcli):" in text
    assert "Bundle run options:" in text
    assert "--prompt" in text
    assert "--num-views" in text
    assert "--benchmark" in text


def test_variant_run_options_are_per_variant_only(tmp_path: Path) -> None:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "q",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "variants": {
            "qwen36": {
                "run_options": [
                    {
                        "name": "K",
                        "type": "integer",
                        "default": 4,
                        "help": "MTP K.",
                        "phase": "load",
                    }
                ]
            }
        },
        "runtime": {"sm120-cu130-linux-x86_64-py312": "runtime/x"},
    }
    manifest = load_bundle_manifest_data(data, bundle_root=tmp_path)
    specs = bundle_run_options(manifest, variant="qwen36")
    assert {s.name for s in specs} == {"K"}


def test_reject_top_level_run_options_when_variants_exist(tmp_path: Path) -> None:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "q",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "run_options": [
            {
                "name": "max_tokens",
                "type": "integer",
                "default": 256,
                "help": "Max tokens.",
                "phase": "predict",
            }
        ],
        "variants": {
            "qwen3": {
                "run_options": [
                    {
                        "name": "prompt",
                        "type": "string",
                        "default": "hi",
                        "help": "Prompt.",
                        "phase": "predict",
                    }
                ]
            }
        },
        "runtime": {"sm120-cu130-linux-x86_64-py312": "runtime/x"},
    }
    manifest = load_bundle_manifest_data(data, bundle_root=tmp_path)
    with pytest.raises(BundleOptionsError, match="must be declared under each variant"):
        bundle_run_options(manifest, variant="qwen3")


def test_run_option_defaults(tmp_path: Path) -> None:
    manifest = _pi05_manifest(tmp_path)
    assert run_option_defaults(manifest) == {
        "prompt": "pick block",
        "num_views": 2,
    }


def test_option_value_uses_manifest_default() -> None:
    from flashcli.bundle.bundle_options import option_value

    defaults = {"max_tokens": 256, "temperature": 0.0}
    assert option_value("max_tokens", {}, defaults) == 256
    assert option_value("max_tokens", {"max_tokens": 64}, defaults) == 64
    assert option_value("seed", {}, defaults) is None


def test_serve_options_split_by_phase(tmp_path: Path) -> None:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "q",
        "python_abi": "312",
        "entry": {"serve": {"module": "serve", "attr": "ServeEngine"}},
        "variants": {
            "qwen3": {
                "serve_options": [
                    {
                        "name": "max_seq",
                        "type": "integer",
                        "default": 2048,
                        "help": "Context.",
                        "phase": "load",
                    },
                    {
                        "name": "warmup",
                        "type": "string",
                        "default": "32:128",
                        "help": "Warmup shapes.",
                        "phase": "warmup",
                    },
                ]
            }
        },
        "runtime": {"sm120-cu130-linux-x86_64-py312": "runtime/x"},
    }
    manifest = load_bundle_manifest_data(data, bundle_root=tmp_path)
    specs = bundle_serve_options(manifest, variant="qwen3")
    load_kw, warmup_kw = split_serve_options(
        {"max_seq": 4096, "warmup": "16:64"}, specs
    )
    assert load_kw == {"max_seq": 4096}
    assert warmup_kw == {"warmup": "16:64"}
    assert serve_option_defaults(manifest, variant="qwen3")["max_seq"] == 2048


def test_format_serve_help(tmp_path: Path) -> None:
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "q",
        "description": "Qwen test",
        "python_abi": "312",
        "entry": {"serve": {"module": "serve", "attr": "ServeEngine"}},
        "variants": {
            "qwen3": {
                "serve_options": [
                    {
                        "name": "max_seq",
                        "type": "integer",
                        "default": 2048,
                        "help": "Context length.",
                        "phase": "load",
                    }
                ]
            }
        },
        "runtime": {"sm120-cu130-linux-x86_64-py312": "runtime/x"},
    }
    manifest = load_bundle_manifest_data(data, bundle_root=tmp_path)
    preset = Preset(
        name="flashcli-bundle/qwen_nvfp4:1.0.1@qwen3",
        raw={"description": "t", "bundle_variant": "qwen3"},
    )
    text = format_serve_help(
        preset,
        manifest,
        bundle_serve_options(manifest, variant="qwen3"),
    )
    assert "Bundle serve options:" in text
    assert "--max-seq" in text
    assert "--port" in text


def test_parse_serve_argv_help(tmp_path: Path, monkeypatch) -> None:
    manifest = load_bundle_manifest_data(
        {
            "format": "flashcli-model-bundle",
            "format_version": 3,
        "protocol_version": 1,
            "name": "q",
            "python_abi": "312",
            "entry": {"serve": {"module": "serve", "attr": "ServeEngine"}},
            "variants": {
                "qwen3": {
                    "serve_options": [
                        {
                            "name": "max_seq",
                            "type": "integer",
                            "default": 2048,
                            "help": "Context.",
                            "phase": "load",
                        }
                    ]
                }
            },
            "runtime": {"sm120-cu130-linux-x86_64-py312": "runtime/x"},
        },
        bundle_root=tmp_path,
    )
    preset = Preset(
        name="flashcli-bundle/qwen_nvfp4:1.0.1@qwen3",
        raw={
            "description": "t",
            "bundle_variant": "qwen3",
            "bundle": {"local_root": str(tmp_path)},
        },
    )
    monkeypatch.setattr(
        "flashcli.bundle.bundle_options.resolve_manifest_for_preset",
        lambda _p, bundle_path=None: manifest,
    )
    inv = parse_serve_argv(
        ["flashcli-bundle/qwen_nvfp4:1.0.1@qwen3", "--help"], preset=preset
    )
    assert inv.help is True
    assert inv.option_specs is not None


def test_parse_run_argv_help(tmp_path: Path, monkeypatch) -> None:
    manifest = _pi05_manifest(tmp_path)
    preset = Preset(
        name="pi05_libero",
        raw={"description": "test", "bundle": {"local_root": str(tmp_path)}},
    )
    monkeypatch.setattr(
        "flashcli.bundle.bundle_options.resolve_manifest_for_preset",
        lambda _p, bundle_path=None: manifest,
    )
    inv = parse_run_argv(["pi05_libero", "--help"], preset=preset)
    assert inv.help is True
    assert inv.option_specs is not None
    assert any(s.name == "prompt" for s in inv.option_specs)


def test_validate_bundle_options_pi05(tmp_path: Path) -> None:
    from flashcli.bundle.bundle_options import validate_bundle_options

    manifest = _pi05_manifest(tmp_path)
    assert validate_bundle_options(manifest) == []


def test_validate_bundle_options_rejects_top_level_with_variants(tmp_path: Path) -> None:
    from flashcli.bundle.bundle_options import validate_bundle_options

    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "q",
        "python_abi": "312",
        "entry": {
            "run": {"module": "run", "attr": "RunEngine"},
            "serve": {"module": "serve", "attr": "ServeEngine"},
        },
        "run_options": [{"name": "prompt", "help": "x", "phase": "predict"}],
        "variants": {
            "qwen3": {
                "run_options": [{"name": "prompt", "help": "x", "phase": "predict"}],
                "serve_options": [{"name": "max_seq", "type": "integer", "default": 1, "help": "x", "phase": "load"}],
            }
        },
        "runtime": {"sm120-cu130-linux-x86_64-py312": "runtime/x"},
    }
    manifest = load_bundle_manifest_data(data, bundle_root=tmp_path)
    with pytest.raises(BundleOptionsError, match="must be declared under each variant"):
        validate_bundle_options(manifest)


def test_resolve_run_from_argv_local_bundle() -> None:
    from flashcli.bundle.bundle_options import resolve_run_from_argv

    preset, bundle_path = resolve_run_from_argv(
        ["run", "bundles/qwen_nvfp4@qwen36"],
        command="run",
    )
    assert preset.bundle_variant == "qwen36"
    assert bundle_path is not None
    assert bundle_path.name == "qwen_nvfp4"


def test_resolve_run_from_argv_flashhub_ref() -> None:
    from flashcli.bundle.bundle_options import resolve_run_from_argv

    preset, bundle_path = resolve_run_from_argv(
        ["run", "flashcli-bundle/qwen_nvfp4:1.0.1@qwen36"],
        command="run",
    )
    assert preset.bundle_variant == "qwen36"
    assert bundle_path is None


def test_validate_repo_bundles() -> None:
    from pathlib import Path

    from flashcli.bundle.bundle_options import validate_bundle_options
    from flashcli.bundle.manifest import load_bundle_manifest

    root = Path(__file__).resolve().parents[1] / "bundles"
    for name in ("pi05_libero", "qwen_nvfp4"):
        manifest = load_bundle_manifest(root / name)
        assert validate_bundle_options(manifest) == [], name


def test_resolve_manifest_skips_stale_cached_repo(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    from flashcli.bundle.bundle_options import resolve_manifest_for_preset
    from flashcli.bundle.marker import write_preset_marker

    monkeypatch.setattr("flashcli.config.BUNDLES_DIR", tmp_path / "bundles")
    bundle_root = tmp_path / "cached"
    bundle_root.mkdir()
    old_manifest = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "name": "pi05_libero",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "runtime": {"sm89-cu130-linux-x86_64-py312": "runtime/x"},
    }
    (bundle_root / "flashcli-bundle.json").write_text(
        json.dumps(old_manifest), encoding="utf-8"
    )
    preset = Preset(
        name="pi05_libero",
        raw={
            "description": "test",
            "bundle": {"repo": "https://flashhub.example/pi05/1.0.3"},
        },
        cache_key="pi05_libero/1.0.3",
    )
    write_preset_marker(
        preset,
        {
            "repo": "https://flashhub.example/pi05/1.0.2",
            "bundle_root": str(bundle_root),
            "runtime_id": "pi05_libero-old",
        },
    )

    fresh = dict(old_manifest)
    fresh["protocol_version"] = 1

    preset = Preset(
        name="pi05_libero",
        raw={
            "description": "test",
            "bundle": {"repo": "https://flashhub.example/pi05/1.0.3"},
        },
        cache_key="pi05_libero/1.0.3",
    )

    monkeypatch.setattr(
        "flashcli.bundle.flashhub.download_manifest_from_repo",
        lambda _repo, _dest, **kw: fresh,
    )

    manifest = resolve_manifest_for_preset(preset)
    assert manifest.raw.get("protocol_version") == 1


def test_resolve_manifest_skips_cache_missing_protocol_version(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    from flashcli.bundle.bundle_options import resolve_manifest_for_preset
    from flashcli.bundle.marker import write_preset_marker

    monkeypatch.setattr("flashcli.config.BUNDLES_DIR", tmp_path / "bundles")
    repo = "https://flashhub.example/pi05/1.0.3"
    bundle_root = tmp_path / "cached"
    bundle_root.mkdir()
    old_manifest = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "name": "pi05_libero",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "runtime": {"sm89-cu130-linux-x86_64-py312": "runtime/x"},
    }
    (bundle_root / "flashcli-bundle.json").write_text(
        json.dumps(old_manifest), encoding="utf-8"
    )
    preset = Preset(
        name="pi05_libero",
        raw={"description": "test", "bundle": {"repo": repo}},
        cache_key="pi05_libero/1.0.4",
    )
    write_preset_marker(
        preset,
        {"repo": repo, "bundle_root": str(bundle_root), "runtime_id": "pi05_libero-x"},
    )

    fresh = dict(old_manifest)
    fresh["protocol_version"] = 1
    preset = Preset(
        name="pi05_libero",
        raw={"description": "test", "bundle": {"repo": repo}},
        cache_key="pi05_libero/1.0.4",
    )
    monkeypatch.setattr(
        "flashcli.bundle.flashhub.download_manifest_from_repo",
        lambda _repo, _dest, **kw: fresh,
    )

    manifest = resolve_manifest_for_preset(preset)
    assert manifest.raw.get("protocol_version") == 1
