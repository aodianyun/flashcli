"""Bootstrap entry for bundle venv — host ``runtime.infer`` only.

Bundle venv Python executes this file by absolute path (see ``reexec.py``).

Loads ``flashcli.runtime.infer`` from the **host** install via
:func:`flashcli.runtime.flashcli_shared.host_flashcli_import_root` — never the full
host ``site-packages`` (see architecture docs on host/bundle isolation).
"""

from __future__ import annotations

import runpy
import sys


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
    from flashcli.runtime.flashcli_shared import host_flashcli_import_root

    entry = str(host_flashcli_import_root())
    if entry not in sys.path:
        sys.path.insert(0, entry)
    runpy.run_module("flashcli.runtime.infer", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
