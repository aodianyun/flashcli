"""Load bundle native extension modules from ``runtime/<env-key>/``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from flashcli_bundle.manifest import (
    BundleManifest,
    bundle_python_abi,
    bundle_python_root,
)
from flashcli_bundle.manifest_ext import bundle_active_native_dir
from flashcli_bundle.native_naming import (
    NativeEnvironmentNotSupportedError,
    discover_native_module_bases,
    logical_native_module_name,
    select_native_module_ranked,
)
from flashcli_bundle.runtime.detect import GpuInfo, detect_gpu_or_raise


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
            import sys as _sys

            raise RuntimeError(
                f"Failed to load native module {path.name}: {exc}\n"
                f"  Current interpreter: Python {_sys.version_info.major}."
                f"{_sys.version_info.minor} ({_sys.executable})\n"
                "  Native modules must load in the bundle venv matching python_abi."
            ) from exc
        if (
            "libcublas" in msg
            or "libcudart" in msg
            or "libcuda" in msg
            or "cuda" in msg.lower()
        ):
            raise RuntimeError(
                f"Failed to load native module {path.name}: {exc}\n"
                "  Install CUDA libs matching the artifact (cu124 → CUDA 12.x, cu130 → CUDA 13.x)\n"
                "  Or set FLASHCLI_CUDA_TAG to pick another native build."
            ) from exc
        raise


def _cuda_runtime_load_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("libcublas", "libcudart", "libcuda", "cannot open shared object")
    )


def _select_loadable_module(
    native_dir: Path,
    module_base: str,
    gpu: GpuInfo,
    *,
    python_minor: str,
) -> Path | None:
    ranked = select_native_module_ranked(
        native_dir, module_base, gpu, allowed_sm=None, python_minor=python_minor
    )
    if not ranked:
        return None
    last_exc: BaseException | None = None
    for candidate in ranked:
        try:
            _probe_so_file(candidate)
            return candidate
        except (ImportError, RuntimeError) as exc:
            last_exc = exc
            if not _cuda_runtime_load_error(exc):
                raise
    if last_exc is not None:
        raise last_exc
    return None


def _resolve_host_native_paths(
    bundle: BundleManifest,
    gpu: GpuInfo,
) -> dict[str, Path]:
    """Pick native modules for this host from ``runtime/<env-key>/``."""
    native_dir = bundle_active_native_dir(bundle, gpu=gpu)
    present = discover_native_module_bases(native_dir)
    if not native_dir.is_dir() or not present:
        raise NativeEnvironmentNotSupportedError(
            module_base="flash_rt_kernels",
            wanted="",
            lib_dir=native_dir,
            available=[],
            gpu=gpu,
        )

    python_minor = bundle_python_abi(bundle)
    paths: dict[str, Path] = {}
    for module_base in present:
        selected = _select_loadable_module(
            native_dir, module_base, gpu, python_minor=python_minor
        )
        if selected is not None:
            paths[module_base] = selected

    if not paths:
        raise NativeEnvironmentNotSupportedError(
            module_base=present[0],
            wanted=f"*py{python_minor}",
            lib_dir=native_dir,
            available=[],
            gpu=gpu,
        )
    return paths


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
    gpu = gpu or detect_gpu_or_raise()
    return _register_from_paths(_resolve_host_native_paths(bundle, gpu))


def verify_native_modules(bundle: BundleManifest, *, gpu: GpuInfo | None = None) -> None:
    gpu = gpu or detect_gpu_or_raise()
    _resolve_host_native_paths(bundle, gpu)


def _probe_so_file(path: Path) -> None:
    name = _so_basename_to_module_name(path.name)
    _load_extension_from_path(path, name)
    for key in (name, f"flash_rt.{name}"):
        sys.modules.pop(key, None)


def probe_native_python_abi(bundle: BundleManifest, *, gpu: GpuInfo | None = None) -> None:
    gpu = gpu or detect_gpu_or_raise()
    paths = _resolve_host_native_paths(bundle, gpu)
    for path in paths.values():
        _probe_so_file(path)
        return


def ensure_bundle_importable(bundle: BundleManifest, *, gpu: GpuInfo | None = None) -> None:
    py_str = str(bundle_python_root(bundle).resolve())
    if py_str not in sys.path:
        sys.path.insert(0, py_str)
    register_native_modules(bundle, gpu=gpu)
