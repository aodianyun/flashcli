"""Bootstrap entry for bundle venv — host ``runtime.infer`` only.

Bundle venv Python executes this file by absolute path (see ``reexec.py``).

- **Bundle entry** (`run.py` / `serve.py`) imports ``flashcli_bundle`` from the bundle
  venv (installed by ``ensure_flashcli_bundle_in_venv``).
- **This launcher** prepends only the **host** flashcli install so
  ``flashcli.runtime.infer`` can run orchestration (weights, activate, re-exec).
  It does **not** pip-install the full flashcli package into the bundle venv.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_LAUNCH = Path(__file__).resolve()
_PKG = _LAUNCH.parent.parent  # ``flashcli`` package directory


def _host_flashcli_sys_path() -> Path:
    """Directory to prepend so ``import flashcli.runtime.infer`` resolves on the host install."""
    candidate_repo = _PKG.parent.parent
    if (candidate_repo / "pyproject.toml").is_file() and (
        candidate_repo / "src" / "flashcli"
    ).is_dir():
        return candidate_repo / "src"
    return _PKG.parent


def _ensure_bundle_protocol_package() -> None:
    try:
        import flashcli_bundle  # noqa: F401
    except ImportError as exc:
        sys.stderr.write(
            "flashcli-bundle is not installed in this bundle venv.\n"
            "Re-run: flashcli run <preset>  (or recreate the bundle runtime venv)\n"
            f"Detail: {exc}\n"
        )
        raise SystemExit(1) from exc


def main() -> None:
    _ensure_bundle_protocol_package()
    entry = str(_host_flashcli_sys_path())
    if entry not in sys.path:
        sys.path.insert(0, entry)
    runpy.run_module("flashcli.runtime.infer", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
