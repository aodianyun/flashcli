"""Host flashcli import path for bundle re-exec — never expose host site-packages."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli import config
from flashcli.runtime.isolation import validate_host_import_root


def is_editable_flashcli() -> bool:
    root = config.package_root()
    return (root / "pyproject.toml").is_file() and (root / "src" / "flashcli").is_dir()


def editable_flashcli_src() -> Path | None:
    if not is_editable_flashcli():
        return None
    return (config.package_root() / "src").resolve()


def installed_flashcli_package_root() -> Path:
    """Top-level ``flashcli`` package directory (``…/site-packages/flashcli``)."""
    return Path(__file__).resolve().parent.parent


def host_flashcli_import_root() -> Path:
    """Path to prepend so bundle venv can ``import flashcli`` without seeing host deps.

    - Editable dev: ``src/`` (contains only ``flashcli/``).
    - Wheel install: ``$FLASHCLI_HOME/host-import/`` with ``flashcli`` → host package
      symlink. Must **not** be the host ``site-packages`` tree (that would expose
      host ``huggingface_hub`` 1.x to bundle ``transformers`` metadata checks).
    """
    dev = editable_flashcli_src()
    if dev is not None:
        validate_host_import_root(dev)
        return dev
    pkg = installed_flashcli_package_root()
    shim_root = (config.FLASHCLI_HOME / "host-import").resolve()
    shim_root.mkdir(parents=True, exist_ok=True)
    link = shim_root / "flashcli"
    target = pkg.resolve()
    if link.is_symlink():
        try:
            if link.resolve() != target:
                link.unlink()
        except OSError:
            link.unlink(missing_ok=True)
    elif link.exists():
        raise RuntimeError(
            f"Host import shim exists but is not a symlink: {link}\n"
            f"Remove it or delete {shim_root} and retry."
        )
    if not link.exists():
        link.symlink_to(target, target_is_directory=True)
    validate_host_import_root(shim_root)
    return shim_root


def host_flashcli_pythonpath() -> str:
    """``PYTHONPATH`` / ``sys.path`` entry for bundle re-exec (host ``flashcli`` only)."""
    return str(host_flashcli_import_root())


def host_flashcli_sys_path_entry() -> Path:
    return host_flashcli_import_root()


def flashcli_pythonpath(*, python_abi: str = "") -> str:
    _ = python_abi
    return host_flashcli_pythonpath()


def prepend_pythonpath(env: dict[str, str], path: str) -> None:
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{path}{os.pathsep}{existing}" if existing else path
