"""Load bundle native extension modules declared in ``flashcli-bundle.json``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from flashcli.bundle.manifest import bundle_modules, bundle_python_root, module_file_path
from flashcli.bundle.manifest import BundleManifest


def _so_basename_to_module_name(filename: str) -> str:
    stem = Path(filename).name
    if stem.endswith(".so"):
        return stem[: -len(".so")]
    return stem


def _load_extension_from_path(path: Path, module_name: str) -> Any:
    path = path.resolve()
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load native module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def register_native_modules(bundle: BundleManifest) -> list[str]:
    """Import ``modules[].file`` and register top-level + ``flash_rt.<name>`` aliases."""
    py_root = bundle_python_root(bundle)
    if (py_root / "flash_rt").is_dir():
        import importlib

        importlib.import_module("flash_rt")

    loaded: list[str] = []
    for entry in bundle_modules(bundle):
        file_rel = str(entry.get("file", "")).strip()
        if not file_rel or not file_rel.endswith(".so"):
            continue
        path = module_file_path(bundle, file_rel)
        if not path.is_file():
            if entry.get("optional"):
                continue
            raise FileNotFoundError(f"Native module file not found: {path}")
        name = _so_basename_to_module_name(path.name)
        mod = _load_extension_from_path(path, name)
        sys.modules[name] = mod
        loaded.append(name)
        flash_rt_pkg = sys.modules.get("flash_rt")
        if flash_rt_pkg is not None:
            setattr(flash_rt_pkg, name, mod)
            sys.modules[f"flash_rt.{name}"] = mod
    return loaded


def verify_native_modules(bundle: BundleManifest) -> None:
    """Ensure required ``modules[]`` files exist (no import — pybind loads once at use)."""
    missing: list[str] = []
    for entry in bundle_modules(bundle):
        if entry.get("optional"):
            continue
        file_rel = str(entry.get("file", "")).strip()
        if not file_rel:
            continue
        path = module_file_path(bundle, file_rel)
        if not path.is_file():
            missing.append(str(path))
    if missing:
        raise RuntimeError(
            "Bundle native modules missing:\n  "
            + "\n  ".join(missing)
            + "\nRebuild the bundle on Linux+GPU (build.sh)."
        )


def ensure_bundle_importable(bundle: BundleManifest) -> None:
    """Prepend bundle python root to ``sys.path`` and optionally preload ``modules``."""
    py_str = str(bundle_python_root(bundle).resolve())
    if py_str not in sys.path:
        sys.path.insert(0, py_str)
    if bundle_modules(bundle):
        register_native_modules(bundle)
