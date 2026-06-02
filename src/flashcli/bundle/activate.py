"""Activate a model-provided runtime bundle on sys.path."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli.bundle.manifest import (
    BundleManifest,
    bundle_cuda_config,
    bundle_python_root,
    check_bundle_python_abi,
)
from flashcli.deps import ensure_runtime_python_stack, bundle_python_stack_satisfied
from flashcli.runtime.detect import torch_index_for_cuda_tag
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
    install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
) -> Path:
    """Put bundle on PYTHONPATH, install inference deps, preload native modules."""
    global _ACTIVE_BUNDLE
    python_root = bundle_python_root(bundle)
    py_str = str(python_root.resolve())
    os.environ["PYTHONPATH"] = py_str + (
        os.pathsep + os.environ["PYTHONPATH"]
        if os.environ.get("PYTHONPATH")
        else ""
    )
    os.environ["FLASHCLI_ACTIVE_BUNDLE"] = str(bundle.bundle_root)
    os.environ["FLASHCLI_ACTIVE_RUNTIME"] = str(bundle.bundle_root)
    _ACTIVE_BUNDLE = bundle

    bundle_root = bundle.bundle_root.resolve()

    from flashcli.runtime.detect import detect_gpu_or_raise

    gpu = detect_gpu_or_raise()
    verify_native_modules(bundle, gpu=gpu)
    check_bundle_python_abi(bundle)
    probe_native_python_abi(bundle, gpu=gpu)

    if install_python:
        cuda = bundle_cuda_config(bundle)
        cuda_tag = str(cuda.get("cuda_tag", ""))
        torch_index = str(cuda.get("recommended_torch_index", "")) or (
            torch_index_for_cuda_tag(cuda_tag) if cuda_tag else "cu124"
        )
        if not force_python and bundle_python_stack_satisfied(
            bundle_root=bundle_root
        ):
            pass
        else:
            if not quiet:
                print(
                    f"Installing bundle Python dependencies (torch/{torch_index}) ..."
                )
            ensure_runtime_python_stack(
                bundle_root=bundle_root,
                torch_index=torch_index,
                quiet=quiet,
                force=force_python,
            )
        if not bundle_python_stack_satisfied(bundle_root=bundle_root):
            if not quiet:
                print("Retrying bundle dependency install ...")
            from flashcli.deps import repair_bundle_python_stack

            repair_bundle_python_stack(
                bundle_root=bundle_root,
                torch_index=torch_index,
                quiet=quiet,
            )

    ensure_bundle_importable(bundle, gpu=gpu)

    return bundle_root


def resolve_torch_index_from_bundle() -> str | None:
    b = _ACTIVE_BUNDLE
    if b is None:
        return None
    cuda = bundle_cuda_config(b)
    idx = cuda.get("recommended_torch_index")
    if idx:
        return str(idx)
    cuda_tag = str(cuda.get("cuda_tag", ""))
    if cuda_tag:
        return torch_index_for_cuda_tag(cuda_tag)
    return None
