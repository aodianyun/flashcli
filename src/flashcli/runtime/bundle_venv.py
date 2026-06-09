"""Per-bundle isolated Python virtualenv."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from flashcli import __version__, config
from flashcli.bundle.manifest import BundleManifest, bundle_python_abi, bundle_torch_index


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
        "flashcli": __version__,
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
    """Create or reuse bundle venv with manifest Python + inference deps + flashcli."""
    python_abi = bundle_python_abi(manifest)
    base_python = resolve_python_for_minor(python_abi)
    if base_python is None:
        major, minor = int(python_abi[0]), int(python_abi[1:])
        raise RuntimeError(
            f"Python 3.{minor} not found for bundle {manifest.name!r}. "
            f"Set FLASHCLI_PY{python_abi}_BIN=/path/to/python{major}.{minor}"
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

    from flashcli import config

    pkg_root = config.package_root()
    if (pkg_root / "pyproject.toml").is_file():
        subprocess.run([str(py), "-m", "pip", "install", "-e", str(pkg_root)], check=True)
    else:
        subprocess.run(
            [str(py), "-m", "pip", "install", f"flashcli=={__version__}"],
            check=True,
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
