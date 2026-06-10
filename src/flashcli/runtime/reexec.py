"""Re-exec into bundle venv infer entry (run/serve only)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flashcli.bundle.artifacts import ensure_runtime_from_path, ensure_runtime_from_repo
from flashcli.bundle.catalog import raw_bundle_cfg, repo_url_for_preset
from flashcli.bundle.preflight import BundleEnvironmentError
from flashcli.bundle.manifest import bundle_python_abi, load_bundle_manifest
from flashcli.models.registry import Preset
from flashcli.runtime.bundle_venv import ensure_bundle_venv, in_bundle_venv, venv_python
from flashcli.runtime.flashcli_shared import (
    ensure_shared_flashcli_lib,
    flashcli_pythonpath,
    is_editable_flashcli,
    prepend_pythonpath,
)


def _resolve_catalog_path(preset: Preset) -> Path | None:
    raw = raw_bundle_cfg(preset)
    path_str = str(raw.get("path", "")).strip()
    if not path_str:
        return None
    from flashcli import config

    raw_path = Path(path_str).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve()
    return (config.package_root() / raw_path).resolve()


def prepare_bundle_runtime(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    quiet: bool = False,
    force: bool = False,
) -> tuple[str, Path]:
    """Download/assemble runtime and ensure bundle venv; return (runtime_id, bundle_root)."""
    if bundle_path is not None:
        runtime_id, bundle_root, manifest, _preflight = ensure_runtime_from_path(
            preset, bundle_path, quiet=quiet
        )
    else:
        local = _resolve_catalog_path(preset)
        if local is not None and local.is_dir():
            runtime_id, bundle_root, manifest, _preflight = ensure_runtime_from_path(
                preset, local, quiet=quiet
            )
        else:
            repo = repo_url_for_preset(preset)
            runtime_id, bundle_root, manifest, _preflight = ensure_runtime_from_repo(
                preset, repo, quiet=quiet, force=force
            )

    ensure_bundle_venv(runtime_id, manifest, quiet=quiet, force=force)
    os.environ.setdefault("FLASHCLI_RUNTIME_ID", runtime_id)
    os.environ.setdefault("FLASHCLI_BUNDLE_ROOT", str(bundle_root))
    return runtime_id, bundle_root


def ensure_bundle_runtime_and_reexec(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    quiet: bool = False,
    force: bool = False,
) -> None:
    """Prepare runtime + venv; re-exec into ``flashcli.runtime.infer`` unless already there."""
    try:
        runtime_id, bundle_root = prepare_bundle_runtime(
            preset,
            bundle_path=bundle_path,
            quiet=quiet,
            force=force,
        )
    except BundleEnvironmentError:
        raise

    if in_bundle_venv(runtime_id):
        os.environ.setdefault("FLASHCLI_BUNDLE_ROOT", str(bundle_root))
        os.environ.setdefault("FLASHCLI_RUNTIME_ID", runtime_id)
        return

    py = venv_python(runtime_id)
    manifest = load_bundle_manifest(bundle_root)
    python_abi = bundle_python_abi(manifest)

    if not is_editable_flashcli():
        ensure_shared_flashcli_lib(py, python_abi, quiet=quiet, force=force)

    env = os.environ.copy()
    env["FLASHCLI_IN_BUNDLE_VENV"] = "1"
    env["FLASHCLI_RUNTIME_ID"] = runtime_id
    env["FLASHCLI_BUNDLE_ROOT"] = str(bundle_root)
    env.pop("PYTHONPATH", None)
    py_path = flashcli_pythonpath(python_abi=python_abi)
    if py_path:
        prepend_pythonpath(env, py_path)
    env["VIRTUAL_ENV"] = str(py.parent.parent)

    argv = [str(py), "-m", "flashcli.runtime.infer", *sys.argv[1:]]
    os.execve(str(py), argv, env)
