"""Activate a model-provided runtime bundle on sys.path."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli_bundle.context import active_bundle, set_active_bundle
from flashcli_bundle.manifest import BundleManifest

from flashcli_bundle.manifest_ext import bundle_torch_index, check_bundle_python_abi
from flashcli_bundle.infer.deps import (
    bundle_python_stack_satisfied,
    ensure_runtime_python_stack,
    repair_bundle_python_stack,
)
from flashcli_bundle.infer.runtime.bundle_venv import venv_python
from flashcli_bundle.native import (
    ensure_bundle_importable,
    probe_native_python_abi,
    verify_native_modules,
)


def activate_bundle(
    bundle: BundleManifest,
    *,
    runtime_id: str | None = None,
    install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
) -> Path:
    """Put bundle on sys.path, install inference deps in bundle venv, preload native."""
    set_active_bundle(bundle)

    bundle_root = bundle.bundle_root.resolve()
    runtime_id = runtime_id or os.environ.get("FLASHCLI_RUNTIME_ID", "")

    from flashcli_bundle.runtime.detect import detect_gpu_or_raise

    gpu = detect_gpu_or_raise()
    verify_native_modules(bundle, gpu=gpu)
    check_bundle_python_abi(bundle)
    probe_native_python_abi(bundle, gpu=gpu)

    pip_python: Path | None = None
    if runtime_id:
        try:
            pip_python = venv_python(runtime_id)
        except FileNotFoundError:
            pip_python = None

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
    from flashcli_bundle.runtime.detect import detect_gpu

    idx = bundle_torch_index(b, gpu=detect_gpu())
    return idx if idx else None


__all__ = ["activate_bundle", "active_bundle", "resolve_torch_index_from_bundle"]
