"""Activate a model-provided runtime bundle on sys.path."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal

from flashcli.bundle.config import bundle_native_runtime
from flashcli.bundle.manifest import BundleManifest, load_runtime_manifest
from flashcli.deps import Profile, ensure_runtime_python_stack, python_stack_satisfied
from flashcli.runtime.detect import torch_index_for_cuda_tag
from flashcli.bundle.native import ensure_runtime_importable, verify_native_libs

ProfileArg = Literal["default", "serve"]

# Per-process active bundle (for doctor / resolve_torch_index).
_ACTIVE_BUNDLE: BundleManifest | None = None


def active_bundle() -> BundleManifest | None:
    return _ACTIVE_BUNDLE


def _sync_partner_runtime(partner_runtime: Path, partner_src: Path) -> None:
    """Point ``runtime/python/partner`` at bundle source (avoid stale copytree)."""
    if not partner_src.is_dir():
        return
    src = partner_src.resolve()
    if partner_runtime.is_symlink():
        try:
            if partner_runtime.resolve() == src:
                return
        except OSError:
            pass
        partner_runtime.unlink()
    elif partner_runtime.exists():
        import shutil

        shutil.rmtree(partner_runtime)
    try:
        partner_runtime.symlink_to(src, target_is_directory=True)
    except OSError:
        import shutil

        shutil.copytree(partner_src, partner_runtime)


def activate_bundle(
    bundle: BundleManifest,
    *,
    profile: ProfileArg = "default",
    install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
) -> Path:
    """Put bundle runtime on PYTHONPATH and optionally install its Python deps."""
    global _ACTIVE_BUNDLE
    runtime_dir = bundle.runtime_dir
    python_root = runtime_dir / "python"
    native = bundle_native_runtime(bundle)
    python_root.mkdir(parents=True, exist_ok=True)
    partner_runtime = python_root / "partner"
    partner_src = bundle.bundle_root / "partner"
    _sync_partner_runtime(partner_runtime, partner_src)
    if not partner_runtime.is_dir():
        raise FileNotFoundError(
            f"Bundle entry modules missing: {partner_runtime} "
            f"(expected {partner_src} or a built runtime/python/partner/)"
        )
    py_str = str(python_root.resolve())
    os.environ["PYTHONPATH"] = py_str + (
        os.pathsep + os.environ["PYTHONPATH"]
        if os.environ.get("PYTHONPATH")
        else ""
    )
    os.environ["FLASHCLI_ACTIVE_BUNDLE"] = str(bundle.bundle_root)
    os.environ["FLASHCLI_ACTIVE_RUNTIME"] = str(runtime_dir)
    _ACTIVE_BUNDLE = bundle

    if install_python:
        manifest = load_runtime_manifest(runtime_dir)
        cuda = manifest.get("cuda", {})
        cuda_tag = str(cuda.get("cuda_tag", ""))
        torch_index = str(cuda.get("recommended_torch_index", "")) or (
            torch_index_for_cuda_tag(cuda_tag) if cuda_tag else "cu124"
        )
        if not force_python and python_stack_satisfied(profile, runtime_dir=runtime_dir):
            pass
        else:
            if not quiet:
                print(
                    f"Installing bundle Python dependencies (torch/{torch_index}) ..."
                )
            ensure_runtime_python_stack(
                runtime_dir=runtime_dir,
                torch_index=torch_index,
                profile=profile,
                quiet=quiet,
                force=force_python,
            )

    if native:
        ensure_runtime_importable(runtime_dir)
        verify_native_libs(runtime_dir=runtime_dir)

    return runtime_dir


def resolve_torch_index_from_bundle() -> str | None:
    b = _ACTIVE_BUNDLE
    if b is None:
        return None
    try:
        manifest = load_runtime_manifest(b.runtime_dir)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    cuda = manifest.get("cuda", {})
    idx = cuda.get("recommended_torch_index")
    if idx:
        return str(idx)
    cuda_tag = str(cuda.get("cuda_tag", ""))
    if cuda_tag:
        return torch_index_for_cuda_tag(cuda_tag)
    return None
