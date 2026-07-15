"""Shared bundle activation core (protocol; pip/venv injected by host or infer)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from flashcli_bundle.context import set_active_bundle
from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.manifest_ext import bundle_torch_index, check_bundle_python_abi
from flashcli_bundle.native import (
    ensure_bundle_importable,
    probe_native_python_abi,
    verify_native_modules,
)
from flashcli_bundle.runtime.detect import detect_gpu, detect_gpu_or_raise

VenvPythonFn = Callable[[str], Path]
StackSatisfiedFn = Callable[..., bool]
InstallStackFn = Callable[..., None]
RepairStackFn = Callable[..., None]


def activate_bundle_core(
    bundle: BundleManifest,
    *,
    runtime_id: str | None = None,
    install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
    venv_python: VenvPythonFn,
    bundle_python_stack_satisfied: StackSatisfiedFn,
    ensure_runtime_python_stack: InstallStackFn,
    repair_bundle_python_stack: RepairStackFn,
) -> Path:
    """Put bundle on sys.path, install inference deps in bundle venv, preload native."""
    set_active_bundle(bundle)

    bundle_root = bundle.bundle_root.resolve()
    runtime_id = runtime_id or os.environ.get("FLASHCLI_RUNTIME_ID", "")

    gpu = detect_gpu_or_raise()

    pip_python: Path | None = None
    if runtime_id:
        try:
            pip_python = venv_python(runtime_id)
        except FileNotFoundError:
            pip_python = None

    # Before dlopen of native .so: ensure libcublas/libcudart for the artifact CUDA tag.
    if pip_python is not None:
        from flashcli_bundle.cuda_userland import ensure_cuda_userland_for_bundle

        ensure_cuda_userland_for_bundle(
            bundle, python=pip_python, gpu=gpu, quiet=quiet
        )

    verify_native_modules(bundle, gpu=gpu)
    check_bundle_python_abi(bundle)
    probe_native_python_abi(bundle, gpu=gpu)

    if install_python:
        torch_index = bundle_torch_index(bundle, gpu=gpu)
        satisfied = (
            pip_python is not None
            and bundle_python_stack_satisfied(
                bundle_root=bundle_root, python=pip_python
            )
        )
        if force_python or not satisfied:
            if not quiet:
                print(
                    f"Installing bundle Python dependencies (torch/{torch_index}) ..."
                )
            ensure_runtime_python_stack(
                bundle_root=bundle_root,
                torch_index=torch_index,
                python=pip_python,
                quiet=quiet,
                force=force_python,
            )
        if pip_python and not bundle_python_stack_satisfied(
            bundle_root=bundle_root, python=pip_python
        ):
            if not quiet:
                print("Retrying bundle dependency install ...")
            repair_bundle_python_stack(
                bundle_root=bundle_root,
                torch_index=torch_index,
                python=pip_python,
                quiet=quiet,
            )

    ensure_bundle_importable(bundle, gpu=gpu)
    return bundle_root


def resolve_torch_index_from_bundle() -> str | None:
    from flashcli_bundle.context import active_bundle as _active

    b = _active()
    if b is None:
        return None
    idx = bundle_torch_index(b, gpu=detect_gpu())
    return idx if idx else None
