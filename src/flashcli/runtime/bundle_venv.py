"""Per-bundle isolated Python virtualenv."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from flashcli.bundle.manifest import BundleManifest, bundle_python_abi, bundle_torch_index
from flashcli.bundle.marker import runtime_dir
from flashcli.bundle.python_install import ensure_python_for_minor
from flashcli.bundle.preflight import BundleEnvironmentError
from flashcli.deps import ensure_runtime_python_stack


def venv_path(runtime_id: str) -> Path:
    return runtime_dir(runtime_id) / "venv"


def fingerprint_path(runtime_id: str) -> Path:
    return runtime_dir(runtime_id) / ".venv-fingerprint"


def venv_python(runtime_id: str) -> Path:
    root = venv_path(runtime_id)
    for name in ("python3", "python"):
        candidate = root / "bin" / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No python in bundle venv: {root}")


def _manifest_fingerprint(manifest: BundleManifest, torch_index: str) -> str:
    payload = {
        "python_abi": bundle_python_abi(manifest),
        "torch_index": torch_index,
        "deps": manifest.raw.get("python_dependencies"),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _create_venv(python_bin: Path, dest: Path) -> None:
    if dest.is_dir():
        import shutil

        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(python_bin), "-m", "venv", str(dest)],
        check=True,
    )


def ensure_bundle_venv(
    runtime_id: str,
    manifest: BundleManifest,
    *,
    quiet: bool = False,
    force: bool = False,
) -> Path:
    """Create or reuse bundle venv with manifest Python + inference deps only."""
    python_abi = bundle_python_abi(manifest)
    try:
        base_python = ensure_python_for_minor(python_abi, quiet=quiet)
    except RuntimeError as exc:
        raise BundleEnvironmentError(str(exc)) from exc
    if base_python is None:
        major, minor = int(python_abi[0]), int(python_abi[1:])
        raise BundleEnvironmentError(
            f"Cannot provision Python 3.{minor} for bundle {manifest.name!r} "
            f"(python_abi={python_abi}).\n"
            f"  Auto-install is disabled (FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON=0).\n"
            f"  Install python{major}.{minor}, set "
            f"FLASHCLI_PY{python_abi}_BIN=/path/to/python{major}.{minor}, "
            f"or re-enable auto-install."
        )

    torch_index = bundle_torch_index(manifest)
    fp = _manifest_fingerprint(manifest, torch_index)
    fp_path = fingerprint_path(runtime_id)
    venv = venv_path(runtime_id)

    if (
        not force
        and venv.is_dir()
        and fp_path.is_file()
        and fp_path.read_text(encoding="utf-8").strip() == fp
    ):
        return venv_python(runtime_id)

    if not quiet:
        print(
            f"Creating bundle venv (Python 3.{python_abi[1:]}) at {venv} ..."
        )
    _create_venv(base_python, venv)
    py = venv_python(runtime_id)

    ensure_runtime_python_stack(
        bundle_root=manifest.bundle_root,
        torch_index=torch_index,
        python=py,
        quiet=quiet,
        force=True,
    )

    fp_path.write_text(fp + "\n", encoding="utf-8")
    return py


def in_bundle_venv(runtime_id: str | None = None) -> bool:
    want = runtime_id or os.environ.get("FLASHCLI_RUNTIME_ID", "")
    if os.environ.get("FLASHCLI_IN_BUNDLE_VENV") != "1":
        return False
    if want and os.environ.get("FLASHCLI_RUNTIME_ID") != want:
        return False
    return True
