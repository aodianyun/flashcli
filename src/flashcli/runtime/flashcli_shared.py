"""Single shared infer bootstrap per (version, python_abi) — not installed into bundle venv."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from flashcli import __version__, config


def is_editable_flashcli() -> bool:
    root = config.package_root()
    return (root / "pyproject.toml").is_file() and (root / "src" / "flashcli").is_dir()


def editable_flashcli_src() -> Path | None:
    if not is_editable_flashcli():
        return None
    return (config.package_root() / "src").resolve()


def shared_flashcli_root(python_abi: str) -> Path:
    return config.FLASHCLI_HOME / "share" / "flashcli" / __version__ / python_abi


def _shared_marker(root: Path) -> Path:
    return root / ".installed"


def ensure_shared_flashcli_lib(
    python: Path,
    python_abi: str,
    *,
    quiet: bool = False,
    force: bool = False,
) -> Path:
    """Install flashcli infer bootstrap once under ``~/.flashcli/share/flashcli/…`` (PYTHONPATH)."""
    if is_editable_flashcli():
        return editable_flashcli_src() or shared_flashcli_root(python_abi)

    root = shared_flashcli_root(python_abi)
    marker = _shared_marker(root)
    if marker.is_file() and not force and (root / "flashcli").is_dir():
        return root

    root.mkdir(parents=True, exist_ok=True)
    pkg_root = config.package_root()
    if (pkg_root / "pyproject.toml").is_file():
        spec = str(pkg_root)
    else:
        spec = f"flashcli=={__version__}"

    if not quiet:
        print(
            f"Installing infer bootstrap {__version__} for Python {python_abi} "
            f"→ {root} (shared, not in bundle venv) …",
            file=sys.stderr,
        )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            spec,
            "--target",
            str(root),
            "--upgrade",
        ],
        check=True,
    )
    marker.write_text(f"{__version__}\n", encoding="utf-8")
    return root


def flashcli_pythonpath(*, python_abi: str) -> str | None:
    """Directory to prepend to ``PYTHONPATH`` so venv python can ``import flashcli``."""
    dev = editable_flashcli_src()
    if dev is not None:
        return str(dev)
    root = shared_flashcli_root(python_abi)
    if (root / "flashcli").is_dir():
        return str(root)
    return None


def prepend_pythonpath(env: dict[str, str], path: str) -> None:
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{path}{os.pathsep}{existing}" if existing else path
