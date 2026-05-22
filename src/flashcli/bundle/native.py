"""Load bundle native extension modules declared in ``flashcli-bundle.json``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from flashcli.bundle.manifest import (
    BundleManifest,
    bundle_modules,
    bundle_native_lib_rel,
    bundle_python_root,
    module_file_path,
)
from flashcli.bundle.native_naming import (
    NativeEnvironmentNotSupportedError,
    bundle_native_lib_dir,
    bundle_uses_native_matrix,
    logical_native_module_name,
    pick_native_so,
    resolve_native_modules_for_host,
)
from flashcli.runtime.detect import GpuInfo, detect_gpu_or_raise


def _so_basename_to_module_name(filename: str) -> str:
    return logical_native_module_name(filename)


def _load_extension_from_path(path: Path, module_name: str) -> Any:
    path = path.resolve()
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load native module from {path}")
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except ImportError as exc:
        msg = str(exc)
        if "Python version mismatch" in msg or "interpreter version is incompatible" in msg:
            import sys

            raise RuntimeError(
                f"Failed to load native module {path.name}: {exc}\n"
                f"  Current interpreter: Python {sys.version_info.major}."
                f"{sys.version_info.minor} ({sys.executable})\n"
                "  This runtime bundle has no matching native build for this Python ABI "
                "under lib/.\n"
                "  Fixes:\n"
                "  - Use a Python version listed in the bundle's native matrix, e.g.:\n"
                "      FLASHCLI_PYTHON=python3.10 flashcli run <preset>\n"
                "  - Or install a bundle build that includes your -pyNNN artifact."
            ) from exc
        if "libcudart" in msg or "libcuda" in msg or "cuda" in msg.lower():
            raise RuntimeError(
                f"Failed to load native module {path.name}: {exc}\n"
                "  The selected .so was built against a CUDA runtime not on LD_LIBRARY_PATH.\n"
                "  Install matching CUDA user-space libraries or use a cu124/cu130 matching host."
            ) from exc
        raise


def _allowed_sm(bundle: BundleManifest) -> list[str] | None:
    req = bundle.raw.get("requires")
    if not isinstance(req, dict):
        return None
    sm = req.get("sm")
    if isinstance(sm, list):
        return [str(x).strip() for x in sm if str(x).strip()]
    if isinstance(sm, str) and sm.strip():
        return [sm.strip()]
    return None


def _native_matrix_enabled(bundle: BundleManifest) -> bool:
    if bundle_uses_native_matrix(bundle.raw):
        lib = bundle_native_lib_dir(bundle.bundle_root, bundle_native_lib_rel(bundle))
        return lib.is_dir() and any(lib.glob("*.so"))
    return False


def _resolve_host_native_paths(
    bundle: BundleManifest,
    gpu: GpuInfo | None = None,
) -> dict[str, Path] | None:
    if not _native_matrix_enabled(bundle):
        return None
    gpu = gpu or detect_gpu_or_raise()
    return resolve_native_modules_for_host(
        bundle.bundle_root,
        gpu,
        native_lib_rel=bundle_native_lib_rel(bundle),
        allowed_sm=_allowed_sm(bundle),
    )


def _register_from_paths(paths: dict[str, Path]) -> list[str]:
    import importlib

    try:
        importlib.import_module("flash_rt")
    except ImportError:
        pass

    loaded: list[str] = []
    for name, path in paths.items():
        mod = _load_extension_from_path(path, name)
        sys.modules[name] = mod
        loaded.append(name)
        flash_rt_pkg = sys.modules.get("flash_rt")
        if flash_rt_pkg is not None:
            setattr(flash_rt_pkg, name, mod)
            sys.modules[f"flash_rt.{name}"] = mod
    return loaded


def register_native_modules(
    bundle: BundleManifest,
    *,
    gpu: GpuInfo | None = None,
) -> list[str]:
    """Load native modules for this host (``lib/`` matrix or legacy ``modules[]``)."""
    matrix_paths = _resolve_host_native_paths(bundle, gpu=gpu)
    if matrix_paths is not None:
        return _register_from_paths(matrix_paths)

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


def verify_native_modules(bundle: BundleManifest, *, gpu: GpuInfo | None = None) -> None:
    """Ensure required native modules exist for this host."""
    try:
        matrix_paths = _resolve_host_native_paths(bundle, gpu=gpu)
    except NativeEnvironmentNotSupportedError:
        raise
    if matrix_paths is not None:
        return

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


def _probe_so_file(path: Path) -> None:
    """Trial-import a .so; undo sys.modules so a later register can run cleanly."""
    name = _so_basename_to_module_name(path.name)
    _load_extension_from_path(path, name)
    for key in (name, f"flash_rt.{name}"):
        sys.modules.pop(key, None)


def _bundle_native_artifact_tag(bundle: BundleManifest) -> str | None:
    build = bundle.raw.get("build") if isinstance(bundle.raw.get("build"), dict) else {}
    tag = build.get("native_artifact_tag")
    return str(tag).strip() if tag else None


def probe_native_python_abi(bundle: BundleManifest, *, gpu: GpuInfo | None = None) -> None:
    """Load one required .so before heavy pip installs — fail fast on ABI mismatch."""
    try:
        matrix_paths = _resolve_host_native_paths(bundle, gpu=gpu)
    except NativeEnvironmentNotSupportedError:
        raise
    if matrix_paths is not None:
        path = matrix_paths.get("flash_rt_kernels") or next(iter(matrix_paths.values()))
        _probe_so_file(path)
        return

    if not bundle_modules(bundle):
        root = bundle.bundle_root.resolve()
        tag = _bundle_native_artifact_tag(bundle)
        lib_rel = bundle_native_lib_rel(bundle)
        for base in ("flash_rt_kernels", "flash_rt_fa2"):
            path = pick_native_so(
                root, base, artifact_tag=tag, native_lib_rel=lib_rel
            )
            if path is not None:
                _probe_so_file(path)
                return
        return

    for entry in bundle_modules(bundle):
        if entry.get("optional"):
            continue
        file_rel = str(entry.get("file", "")).strip()
        if not file_rel or not file_rel.endswith(".so"):
            continue
        path = module_file_path(bundle, file_rel)
        if path.is_file():
            _probe_so_file(path)
            return


def ensure_bundle_importable(bundle: BundleManifest, *, gpu: GpuInfo | None = None) -> None:
    """Prepend bundle python root to ``sys.path`` and preload native modules."""
    py_str = str(bundle_python_root(bundle).resolve())
    if py_str not in sys.path:
        sys.path.insert(0, py_str)
    if _native_matrix_enabled(bundle) or bundle_modules(bundle):
        register_native_modules(bundle, gpu=gpu)
