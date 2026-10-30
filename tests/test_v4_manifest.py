from pathlib import Path

import pytest

from flashcli_bundle.manifest import load_bundle_manifest_data
from flashcli_bundle.weights import extra_weight_dest, weights_store_key


def _v4():
    return {
        "format": "flashcli-model-bundle",
        "format_version": 4,
        "protocol_version": 1,
        "name": "demo",
        "build": {
            "flashrt_tag": "v0.2.0-39-g66b18eb7",
            "git_commit": "66b18eb766e73e2fcad406bc622bd3bfd70664c1",
        },
        "defaults": {
            "entry": {"run": {"module": "run", "attr": "RunEngine"}},
            "python_abi": "312",
            "python_dependencies": {"pip": ["numpy"]},
            "weights": {"source": "huggingface", "repo": "org/demo", "revision": "main"},
        "extra_weights": {
            "tokenizer": {
                "source": "huggingface",
                "repo": "org/tokenizer",
                "revision": "main",
            }
        },
        },
        "environments": {
            "linux": {
                "runtime": "runtime/linux",
                "python_dependencies": {"pip": ["numpy", "triton"]},
            },
            "windows": {
                "runtime": "runtime/windows",
                "python_dependencies": {"pip": ["numpy"]},
            },
        },
    }


def test_v4_selects_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLASHCLI_RUNTIME_ENV_KEY", "linux")
    m = load_bundle_manifest_data(_v4(), bundle_root=tmp_path)
    assert m.raw["python_dependencies"]["pip"] == ["numpy", "triton"]
    assert m.raw["runtime"] == {
        "linux": "runtime/linux",
        "windows": "runtime/windows",
    }
    assert m.entry_run is not None
    assert m.raw["build"]["flashrt_tag"] == "v0.2.0-39-g66b18eb7"
    assert m.raw["build"]["git_commit"] == "66b18eb766e73e2fcad406bc622bd3bfd70664c1"
    tokenizer = m.raw["extra_weights"]["tokenizer"]
    assert tokenizer["weights_dir"] == "extra/tokenizer"
    assert extra_weight_dest(m, "tokenizer", tokenizer, checkpoint_dir=tmp_path / "store") == tmp_path / "store/extra/tokenizer"
    assert weights_store_key(m).startswith("store/huggingface/org__demo@main-")


def test_v4_requires_env_when_ambiguous(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FLASHCLI_RUNTIME_ENV_KEY", raising=False)
    with pytest.raises(ValueError, match="FLASHCLI_RUNTIME_ENV_KEY"):
        load_bundle_manifest_data(_v4(), bundle_root=tmp_path)


def test_v4_rejects_variants(tmp_path: Path) -> None:
    data = _v4()
    data["variants"] = {"x": {}}
    with pytest.raises(ValueError, match="does not support variants"):
        load_bundle_manifest_data(data, bundle_root=tmp_path)
