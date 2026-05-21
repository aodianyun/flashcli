"""Link bundle native libs into runtime/python for import."""

from __future__ import annotations

import sys
from pathlib import Path


def _kernels_so_path(runtime_dir: Path) -> Path | None:
    for candidate in (
        runtime_dir / "lib" / "flash_rt_kernels.so",
        runtime_dir / "python" / "flash_rt" / "flash_rt_kernels.so",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def verify_native_libs(*, runtime_dir: Path) -> None:
    """Ensure required ``.so`` files exist (no import — pybind11 must load once)."""
    so = _kernels_so_path(runtime_dir)
    if so is None or not so.is_file():
        raise RuntimeError(
            f"flash_rt_kernels.so not found under {runtime_dir}/lib/. "
            "Run the bundle build.sh on Linux+GPU first."
        )


def _link_into(py_pkg: Path, lib_dir: Path) -> None:
    py_pkg.mkdir(parents=True, exist_ok=True)
    for so in lib_dir.glob("*.so"):
        dest = py_pkg / so.name
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink():
                dest.unlink()
            elif dest.samefile(so):
                continue
            else:
                dest.unlink()
        dest.symlink_to(so.resolve())


def link_native_libs(runtime_dir: Path) -> None:
    """Symlink ``runtime/lib/*.so`` into ``runtime/python/flash_rt`` and ``partner``."""
    lib_dir = runtime_dir / "lib"
    if not lib_dir.is_dir():
        return
    py_root = runtime_dir / "python"
    if py_root.is_dir():
        for stale in py_root.rglob("*.so"):
            if stale.is_symlink():
                stale.unlink()
            elif stale.is_file():
                stale.unlink()
    for pkg_name in ("partner", "flash_rt"):
        py_pkg = py_root / pkg_name
        if py_pkg.is_dir():
            _link_into(py_pkg, lib_dir)


def ensure_runtime_importable(runtime_dir: Path) -> None:
    """Link native libs and prepend ``runtime/python`` to ``sys.path``."""
    link_native_libs(runtime_dir)
    py_str = str((runtime_dir / "python").resolve())
    if py_str not in sys.path:
        sys.path.insert(0, py_str)
