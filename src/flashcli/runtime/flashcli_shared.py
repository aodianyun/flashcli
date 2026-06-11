"""Host flashcli on PYTHONPATH for bundle re-exec — never pip-install flashcli into bundle venv."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli import config


def is_editable_flashcli() -> bool:
    root = config.package_root()
    return (root / "pyproject.toml").is_file() and (root / "src" / "flashcli").is_dir()


def editable_flashcli_src() -> Path | None:
    if not is_editable_flashcli():
        return None
    return (config.package_root() / "src").resolve()


def installed_flashcli_pkg_dir() -> Path:
    """Directory of the currently running ``flashcli`` package."""
    return Path(__file__).resolve().parent


def host_flashcli_pythonpath() -> str:
    """``PYTHONPATH`` entry so bundle venv python can ``import flashcli`` from the host install."""
    dev = editable_flashcli_src()
    if dev is not None:
        return str(dev)
    return str(installed_flashcli_pkg_dir().parent)


def host_flashcli_sys_path_entry() -> Path:
    """Same directory as :func:`host_flashcli_pythonpath`, as a :class:`Path`."""
    return Path(host_flashcli_pythonpath())


def flashcli_pythonpath(*, python_abi: str = "") -> str:
    """Alias kept for callers; host install is shared across bundle Python ABIs."""
    _ = python_abi
    return host_flashcli_pythonpath()


def prepend_pythonpath(env: dict[str, str], path: str) -> None:
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{path}{os.pathsep}{existing}" if existing else path
