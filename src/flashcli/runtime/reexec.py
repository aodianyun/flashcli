"""Re-exec into bundle venv infer entry (run/serve only).

Host CLI (``cli.py``) prepares runtime + bundle venv, then execs:

  bundle_venv/python -m flashcli_bundle.infer run|serve …

The bundle venv pip-installs ``flashcli-bundle[infer]``; no host ``flashcli`` import.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flashcli.bundle.artifacts import ensure_runtime_from_path, ensure_runtime_from_repo
from flashcli.bundle.catalog import raw_bundle_cfg, repo_url_for_preset
from flashcli.bundle.preflight import BundleEnvironmentError
from flashcli.bundle.manifest import load_bundle_manifest
from flashcli.deps import ensure_flashcli_bundle_in_venv
from flashcli.models.registry import Preset
from flashcli.runtime.bundle_venv import ensure_bundle_venv, in_bundle_venv, venv_python


def _resolve_local_root(preset: Preset) -> Path | None:
    raw = raw_bundle_cfg(preset)
    path_str = str(raw.get("local_root", "")).strip()
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
        local = _resolve_local_root(preset)
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
    """Prepare runtime + venv; re-exec into ``flashcli_bundle.infer`` unless already there."""
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
    ensure_flashcli_bundle_in_venv(
        python=py, quiet=quiet, force=force, extras=("infer",)
    )

    env = os.environ.copy()
    env["FLASHCLI_IN_BUNDLE_VENV"] = "1"
    env["FLASHCLI_RUNTIME_ID"] = runtime_id
    env["FLASHCLI_BUNDLE_ROOT"] = str(bundle_root)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONSAFEPATH", None)
    env["VIRTUAL_ENV"] = str(py.parent.parent)

    argv = [str(py), "-m", "flashcli_bundle.infer", *sys.argv[1:]]
    os.execve(str(py), argv, env)
