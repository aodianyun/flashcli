"""Build-time import probe for vendored gr00t/ under the bundle root."""

from __future__ import annotations

import compileall
import json
import os
import subprocess
import sys
from pathlib import Path

BUNDLE_DIR = Path(__file__).resolve().parent
VENDOR_ROOT = BUNDLE_DIR / "gr00t"
VENDOR_META = VENDOR_ROOT / "VENDOR.json"

_REQUIRED_PATHS = (
    VENDOR_ROOT / "policy" / "gr00t_policy.py",
    VENDOR_ROOT / "model" / "gr00t_n1d7",
    VENDOR_ROOT / "data" / "embodiment_tags.py",
    VENDOR_ROOT / "eval" / "open_loop_eval.py",
)

_FULL_PROBE_SCRIPT = """
import gr00t.model.gr00t_n1d7.gr00t_n1d7  # noqa: F401
from gr00t.data.embodiment_tags import EmbodimentTag
from gr00t.policy.gr00t_policy import Gr00tPolicy

EmbodimentTag.resolve("oxe_droid_relative_eef_relative_joint")
print("gr00t vendor import probe OK")
"""


def _pythonpath_env(bundle_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    root = str(bundle_root.resolve())
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root + (os.pathsep + prev if prev else "")
    return env


def verify_layout() -> None:
    if not VENDOR_ROOT.is_dir():
        raise SystemExit(f"Missing vendored tree: {VENDOR_ROOT}")
    if not VENDOR_META.is_file():
        raise SystemExit(f"Missing vendored metadata: {VENDOR_META}")
    meta = json.loads(VENDOR_META.read_text(encoding="utf-8"))
    for key in ("repo", "git_ref", "commit"):
        if not meta.get(key):
            raise SystemExit(f"VENDOR.json missing {key!r}")
    missing = [str(p.relative_to(BUNDLE_DIR)) for p in _REQUIRED_PATHS if not p.exists()]
    if missing:
        raise SystemExit("Vendored gr00t layout incomplete: " + ", ".join(missing))


def verify_compiles() -> None:
    ok = compileall.compile_dir(
        str(VENDOR_ROOT),
        quiet=1,
        legacy=False,
    )
    if not ok:
        raise SystemExit(f"Vendored gr00t compile check failed under {VENDOR_ROOT}")


def _runtime_deps_available(python: str) -> bool:
    proc = subprocess.run(
        [python, "-c", "import numpy, torch, transformers, tyro, tqdm"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def verify_imports(*, python: str | None = None) -> None:
    py = python or sys.executable
    if not _runtime_deps_available(py):
        print(
            "gr00t vendor import probe skipped "
            f"(runtime deps not installed under {py})",
            file=sys.stderr,
        )
        return
    proc = subprocess.run(
        [py, "-c", _FULL_PROBE_SCRIPT],
        env=_pythonpath_env(BUNDLE_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(
            f"gr00t vendor import probe failed under {py}:\n{stderr}"
        )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    python = None
    if argv and argv[0] == "--python":
        if len(argv) < 2:
            print("--python requires a path", file=sys.stderr)
            return 2
        python = argv[1]
    try:
        verify_layout()
        verify_compiles()
        verify_imports(python=python)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    print("gr00t vendor verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
