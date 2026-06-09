"""Activate a model-provided runtime bundle on sys.path."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli.bundle.manifest import (
    BundleManifest,
    bundle_torch_index,
    check_bundle_python_abi,
)
from flashcli.deps import (
    bundle_python_stack_satisfied,
    ensure_runtime_python_stack,
    repair_bundle_python_stack,
)
from flashcli.runtime.bundle_venv import venv_python
from flashcli.bundle.native import (
    ensure_bundle_importable,
    probe_native_python_abi,
    verify_native_modules,
)

_ACTIVE_BUNDLE: BundleManifest | None = None


def active_bundle() -> BundleManifest | None:
    return _ACTIVE_BUNDLE


def activate_bundle(
    bundle: BundleManifest,
    *,
    runtime_id: str | None = None,
    install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
) -> Path:
    """Put bundle on sys.path, install inference deps in bundle venv, preload native."""
    global _ACTIVE_BUNDLE
    _ACTIVE_BUNDLE = bundle
    os.environ["FLASHCLI_ACTIVE_BUNDLE"] = str(bundle.bundle_root)
    os.environ["FLASHCLI_ACTIVE_RUNTIME"] = str(bundle.bundle_root)

    bundle_root = bundle.bundle_root.resolve()
    runtime_id = runtime_id or os.environ.get("FLASHCLI_RUNTIME_ID", "")

    from flashcli.runtime.detect import detect_gpu_or_raise

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
        torch_index = bundle_torch_index(bundle)
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
    b = _ACTIVE_BUNDLE
    if b is None:
        return None
    idx = bundle_torch_index(b)
    return idx if idx else None
