"""Resolve standalone Python interpreters for host install / ABI probe (host only)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from flashcli.bundle.python_paths import bundle_python_root, load_python_env_file
from flashcli_bundle.runtime_env import host_python_minor


def _python_roots() -> list[str]:
    roots: list[str] = []
    override = os.environ.get("FLASHCLI_PYTHON_ROOT", "").strip()
    if override:
        roots.append(override)
    roots.append(str(bundle_python_root()))
    roots.append("/opt/flashcli-python")
    seen: set[str] = set()
    out: list[str] = []
    for root in roots:
        if root and root not in seen:
            seen.add(root)
            out.append(root)
    return out


def _python_candidates(py_minor: str) -> list[str]:
    if not py_minor.isdigit() or len(py_minor) != 3:
        return []
    major, minor = py_minor[0], py_minor[1:]
    ver = f"python{major}.{minor}"
    override = os.environ.get(f"FLASHCLI_PY{py_minor}_BIN", "").strip()
    out: list[str] = []
    if override:
        out.append(override)
    mm = f"{major}.{minor}"
    for root in _python_roots():
        out.extend(
            [
                f"{root}/{mm}/bin/{ver}",
                f"{root}/{mm}/bin/python3",
            ]
        )
    out.extend(
        [
            f"/opt/python/{ver}/bin/{ver}",
            f"/usr/local/bin/{ver}",
            f"/usr/bin/{ver}",
            ver,
        ]
    )
    if host_python_minor() == py_minor:
        out.append(sys.executable)
    return out


def python_can_create_venv(py_bin: Path) -> bool:
    """True when *py_bin* can run ``python -m venv`` (Debian may split ensurepip)."""
    try:
        proc = subprocess.run(
            [str(py_bin), "-c", "import ensurepip, venv"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _python_reports_minor(py_bin: Path, py_minor: str) -> bool:
    try:
        out = subprocess.run(
            [str(py_bin), "-c", "import sys; print(sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if out.returncode != 0:
        return False
    m = re.match(r"\((\d+), (\d+)\)", out.stdout.strip())
    if not m:
        return False
    return int(m.group(1)) == int(py_minor[0]) and int(m.group(2)) == int(py_minor[1:])


def _resolve_candidate_path(cand: str) -> Path | None:
    if "/" in cand or cand.startswith("."):
        p = Path(cand)
        if p.is_file() and os.access(p, os.X_OK):
            return p
        return None
    found = shutil.which(cand)
    if not found:
        return None
    p = Path(found)
    if p.is_file() and os.access(p, os.X_OK):
        return p
    return None


def resolve_python_for_minor(
    py_minor: str,
    *,
    require_venv: bool = False,
) -> Path | None:
    load_python_env_file()
    seen: set[str] = set()
    for cand in _python_candidates(py_minor):
        p = _resolve_candidate_path(cand)
        if p is None:
            continue
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        if not _python_reports_minor(p, py_minor):
            continue
        if require_venv and not python_can_create_venv(p):
            continue
        return p.resolve()
    return None
