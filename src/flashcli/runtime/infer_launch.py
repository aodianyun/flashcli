"""Bootstrap entry for bundle venv — load host flashcli, then run ``runtime.infer``.

Bundle venv Python executes this file by absolute path (see ``reexec.py``). This
module must not ``import flashcli`` before adjusting ``sys.path``.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_LAUNCH = Path(__file__).resolve()
_PKG = _LAUNCH.parent.parent  # ``flashcli`` package directory


def _host_sys_path_entry() -> Path:
    candidate_repo = _PKG.parent.parent
    if (candidate_repo / "pyproject.toml").is_file() and (
        candidate_repo / "src" / "flashcli"
    ).is_dir():
        return candidate_repo / "src"
    return _PKG.parent


def main() -> None:
    entry = str(_host_sys_path_entry())
    if entry not in sys.path:
        sys.path.insert(0, entry)
    runpy.run_module("flashcli.runtime.infer", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
