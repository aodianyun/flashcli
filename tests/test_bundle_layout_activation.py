"""Layout/activation rules for manifest-driven runtime directories."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from flashcli_bundle.manifest import load_bundle_manifest
from flashcli_bundle.manifest_ext import validate_bundle_layout
from flashcli_bundle.native import ensure_bundle_importable

ENV_KEY = "sm120-cu130-linux-x86_64-py312"


def _write_bundle(root: Path, *, per_env_flash_rt: bool, root_flash_rt: bool) -> Path:
    manifest = {
        "format": "flashcli-model-bundle",
        "format_version": 4,
        "protocol_version": 1,
        "name": "layout_demo",
        "defaults": {
            "python_abi": "312",
            "python_dependencies": {"torch": False, "pip": []},
            "run_options": [{"name": "prompt", "type": "string", "help": "p"}],
            "weights": {
                "source": "huggingface",
                "repo": "example/layout",
                "revision": "0123456789abcdef0123456789abcdef01234567",
            },
        },
        "environments": {
            ENV_KEY: {
                "runtime": ENV_KEY,
                "entry": {
                    "run": {"kind": "python", "module": f"{ENV_KEY}.run", "attr": "RunEngine"}
                },
            }
        },
    }
    (root / "flashcli-bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    env_dir = root / ENV_KEY
    env_dir.mkdir()
    (env_dir / "run.py").write_text("class RunEngine:\n    pass\n", encoding="utf-8")
    (env_dir / "helper.py").write_text("VALUE = 7\n", encoding="utf-8")
    if per_env_flash_rt:
        pkg = env_dir / "flash_rt"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("SOURCE = 'runtime'\n", encoding="utf-8")
    if root_flash_rt:
        pkg = root / "flash_rt"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("SOURCE = 'root'\n", encoding="utf-8")
    return env_dir


@pytest.fixture(autouse=True)
def _env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLASHCLI_RUNTIME_ENV_KEY", ENV_KEY)
    for name in list(sys.modules):
        if name == "flash_rt" or name.startswith("flash_rt."):
            sys.modules.pop(name, None)
    sys.modules.pop("helper", None)


def _isolate_flash_rt_paths() -> list[str]:
    """Drop other tests' bundle roots so ``flash_rt`` resolves from this fixture."""
    old = list(sys.path)
    sys.path[:] = [
        p for p in sys.path if not p or not (Path(p) / "flash_rt").is_dir()
    ]
    return old


def test_layout_allows_python_runtime_dir_without_flash_rt_or_so(tmp_path: Path) -> None:
    _write_bundle(tmp_path, per_env_flash_rt=False, root_flash_rt=False)
    bundle = load_bundle_manifest(tmp_path)
    assert validate_bundle_layout(bundle, env_key=ENV_KEY) == []


def test_runtime_dir_is_appended_to_sys_path(tmp_path: Path) -> None:
    env_dir = _write_bundle(tmp_path, per_env_flash_rt=True, root_flash_rt=False)
    bundle = load_bundle_manifest(tmp_path)
    old_path = _isolate_flash_rt_paths()
    try:
        ensure_bundle_importable(bundle)
        assert str(env_dir.resolve()) in sys.path
        rt = importlib.import_module("flash_rt")
        assert rt.SOURCE == "runtime"
        helper = importlib.import_module("helper")
        assert helper.VALUE == 7
    finally:
        sys.path[:] = old_path
        sys.modules.pop("flash_rt", None)
        sys.modules.pop("helper", None)


def test_root_flash_rt_wins_over_runtime_flash_rt(tmp_path: Path) -> None:
    _write_bundle(tmp_path, per_env_flash_rt=True, root_flash_rt=True)
    bundle = load_bundle_manifest(tmp_path)
    old_path = _isolate_flash_rt_paths()
    try:
        ensure_bundle_importable(bundle)
        rt = importlib.import_module("flash_rt")
        assert rt.SOURCE == "root"
    finally:
        sys.path[:] = old_path
        sys.modules.pop("flash_rt", None)
