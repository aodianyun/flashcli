"""Activate a model-provided runtime bundle on sys.path (host deps injection)."""

from __future__ import annotations

from pathlib import Path

from flashcli_bundle.activate_core import (
    activate_bundle_core,
    resolve_torch_index_from_bundle,
)
from flashcli_bundle.context import active_bundle
from flashcli_bundle.manifest import BundleManifest

from flashcli.deps import (
    bundle_python_stack_satisfied,
    ensure_runtime_python_stack,
    repair_bundle_python_stack,
)
from flashcli.runtime.bundle_venv import venv_python


def activate_bundle(
    bundle: BundleManifest,
    *,
    runtime_id: str | None = None,
    install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
) -> Path:
    return activate_bundle_core(
        bundle,
        runtime_id=runtime_id,
        install_python=install_python,
        quiet=quiet,
        force_python=force_python,
        venv_python=venv_python,
        bundle_python_stack_satisfied=bundle_python_stack_satisfied,
        ensure_runtime_python_stack=ensure_runtime_python_stack,
        repair_bundle_python_stack=repair_bundle_python_stack,
    )


__all__ = ["activate_bundle", "active_bundle", "resolve_torch_index_from_bundle"]
