"""Orchestrate flashcli CLI dependencies."""

from __future__ import annotations

from flashcli.deps import ensure_flashcli_stack, flashcli_stack_satisfied
from flashcli.runtime.detect import detect_gpu, torch_index_for_cuda_tag


def resolve_torch_index() -> str:
    """Prefer active model bundle manifest, then local GPU detection."""
    from flashcli.bundle.activate import resolve_torch_index_from_bundle

    idx = resolve_torch_index_from_bundle()
    if idx:
        return idx
    gpu = detect_gpu()
    if gpu is not None:
        return gpu.recommended_torch_index
    return "cu124"


def ensure_environment(
    *,
    install_flashcli: bool = False,
    include_serve: bool = False,
    quiet: bool = False,
    force: bool = False,
) -> None:
    """Install missing flashcli dependencies (core; + serve HTTP stack when requested)."""
    if not install_flashcli:
        return
    if not force and flashcli_stack_satisfied(include_serve=include_serve):
        return
    if not quiet:
        label = "flashcli + serve" if include_serve else "flashcli"
        print(f"Ensuring {label} Python dependencies ...")
    ensure_flashcli_stack(
        quiet=quiet, force=force, include_serve=include_serve
    )


__all__ = ["ensure_environment", "resolve_torch_index", "torch_index_for_cuda_tag"]
