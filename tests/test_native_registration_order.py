"""Native modules must register before bundle ``flash_rt.api`` caches kernel handles."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

from flashcli_bundle import native as native_mod


@pytest.fixture
def bundle_flash_rt_tree(tmp_path: Path):
    root = tmp_path / "bundle"
    pkg = root / "flash_rt"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "from flash_rt.api import inject\n",
        encoding="utf-8",
    )
    (pkg / "api.py").write_text(
        """
try:
    from flash_rt import flash_rt_kernels as _fvk
except ImportError:
    try:
        import flash_rt_kernels as _fvk
    except ImportError:
        _fvk = None

try:
    from flash_rt import flash_rt_omnivoice as _fvo
except ImportError:
    try:
        import flash_rt_omnivoice as _fvo
    except ImportError:
        _fvo = None

_has_cfg_kernel = _fvo is not None and hasattr(_fvo, "omnivoice_cfg_logsoftmax_bf16")

def inject():
    if _fvk is None or _fvo is None:
        raise RuntimeError("kernels missing")
""",
        encoding="utf-8",
    )
    return root


def _cleanup_flash_rt_modules() -> None:
    for key in list(sys.modules):
        if key == "flash_rt" or key.startswith("flash_rt."):
            del sys.modules[key]
        if key in ("flash_rt_kernels", "flash_rt_omnivoice", "flash_rt_fa2"):
            del sys.modules[key]


def test_register_natives_before_flash_rt_api_import(bundle_flash_rt_tree: Path, monkeypatch):
    fake_kernels = types.ModuleType("flash_rt_kernels")
    fake_omni = types.ModuleType("flash_rt_omnivoice")
    fake_omni.omnivoice_cfg_logsoftmax_bf16 = object()

    def fake_load(_path: Path, name: str):
        if name == "flash_rt_kernels":
            return fake_kernels
        if name == "flash_rt_omnivoice":
            return fake_omni
        raise AssertionError(f"unexpected module {name!r}")

    monkeypatch.setattr(native_mod, "_load_extension_from_path", fake_load)

    paths = {
        "flash_rt_kernels": bundle_flash_rt_tree / "runtime/x/flash_rt_kernels.so",
        "flash_rt_omnivoice": bundle_flash_rt_tree / "runtime/x/flash_rt_omnivoice.so",
    }

    root_str = str(bundle_flash_rt_tree)
    sys.path.insert(0, root_str)
    _cleanup_flash_rt_modules()
    try:
        native_mod._register_from_paths(paths)
        api = importlib.import_module("flash_rt.api")
        api.inject()
    finally:
        if root_str in sys.path:
            sys.path.remove(root_str)
        _cleanup_flash_rt_modules()


def test_refresh_kernel_bindings_after_early_api_import(
    bundle_flash_rt_tree: Path, monkeypatch
):
    fake_kernels = types.ModuleType("flash_rt_kernels")
    fake_omni = types.ModuleType("flash_rt_omnivoice")
    fake_omni.omnivoice_cfg_logsoftmax_bf16 = object()

    def fake_load(_path: Path, name: str):
        if name == "flash_rt_kernels":
            return fake_kernels
        if name == "flash_rt_omnivoice":
            return fake_omni
        raise AssertionError(f"unexpected module {name!r}")

    monkeypatch.setattr(native_mod, "_load_extension_from_path", fake_load)

    paths = {
        "flash_rt_kernels": bundle_flash_rt_tree / "runtime/x/flash_rt_kernels.so",
        "flash_rt_omnivoice": bundle_flash_rt_tree / "runtime/x/flash_rt_omnivoice.so",
    }

    root_str = str(bundle_flash_rt_tree)
    sys.path.insert(0, root_str)
    _cleanup_flash_rt_modules()
    try:
        api = importlib.import_module("flash_rt.api")
        assert api._fvk is None
        assert api._fvo is None

        native_mod._register_from_paths(paths)
        api.inject()
    finally:
        if root_str in sys.path:
            sys.path.remove(root_str)
        _cleanup_flash_rt_modules()
