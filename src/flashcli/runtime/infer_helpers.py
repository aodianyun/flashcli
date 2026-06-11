"""Shared helpers for bundle inference (run/serve) inside the bundle venv."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from flashcli import config
from flashcli.bundle.manifest import bundle_torch_index


def auto_install_flag(no_auto_install: bool) -> bool:
    return not no_auto_install and not config.skip_auto_install()


def retry_after_bundle_repair(
    action,
    *,
    bundle,
    auto_install: bool,
    quiet: bool,
):
    """Run *action*; on ImportError auto-install missing bundle deps and retry once."""
    try:
        return action()
    except ImportError:
        if not auto_install or bundle is None:
            raise
        from flashcli.deps import repair_bundle_python_stack
        from flashcli.runtime.bundle_venv import venv_python

        runtime_id = os.environ.get("FLASHCLI_RUNTIME_ID", "")
        py = venv_python(runtime_id) if runtime_id else None

        if not quiet:
            typer.echo("Missing bundle dependency; installing ...", err=True)
        repair_bundle_python_stack(
            bundle_root=bundle.bundle_root,
            torch_index=bundle_torch_index(bundle),
            python=py,
            quiet=quiet,
        )
        return action()


def ensure_flashcli_serve_imports(*, auto_install: bool, quiet: bool) -> None:
    """Verify HTTP stack imports (fastapi/uvicorn) in the bundle venv."""
    try:
        __import__("fastapi")
        __import__("uvicorn")
    except ImportError as exc:
        if not auto_install:
            raise
        from flashcli.deps import ensure_bundle_infer_deps
        from flashcli.runtime.bundle_venv import venv_python

        runtime_id = os.environ.get("FLASHCLI_RUNTIME_ID", "")
        py = venv_python(runtime_id) if runtime_id else None
        if py is not None:
            ensure_bundle_infer_deps(python=py, quiet=quiet, force=True)
        __import__("fastapi")
        __import__("uvicorn")
