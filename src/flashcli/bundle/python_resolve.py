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
    out.extend(
        [
            ver,
            f"/usr/local/bin/{ver}",
            f"/usr/bin/{ver}",
        ]
    )
    for root in _python_roots():
        mm = f"{major}.{minor}"
        out.extend(
            [
                f"{root}/{mm}/bin/{ver}",
                f"{root}/{mm}/bin/python3",
            ]
        )
    out.append(f"/opt/python/{ver}/bin/{ver}")
    return out


def resolve_python_for_minor(py_minor: str) -> Path | None:
    load_python_env_file()
    if host_python_minor() == py_minor:
        return Path(sys.executable)
    for cand in _python_candidates(py_minor):
        if "/" in cand:
            p = Path(cand)
            if not (p.is_file() and os.access(p, os.X_OK)):
                continue
        else:
            found = shutil.which(cand)
            if not found:
                continue
            p = Path(found)
        try:
            out = subprocess.run(
                [str(p), "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode != 0:
            continue
        m = re.match(r"\((\d+), (\d+)\)", out.stdout.strip())
        if not m:
            continue
        if int(m.group(1)) == int(py_minor[0]) and int(m.group(2)) == int(py_minor[1:]):
            return p.resolve()
    return None
