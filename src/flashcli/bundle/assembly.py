"""Detect whether a local bundle.path tree is built and ready to run."""

from __future__ import annotations

import json
from pathlib import Path


def bundle_build_script(root: Path) -> Path | None:
    script = root.resolve() / "build.sh"
    return script if script.is_file() else None


def describe_bundle_assembly_gaps(root: Path) -> list[str]:
    root = root.resolve()
    gaps: list[str] = []

    bundle_json = root / "flashcli-bundle.json"
    if not bundle_json.is_file():
        gaps.append("missing flashcli-bundle.json")
        return gaps

    try:
        data = json.loads(bundle_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        gaps.append(f"flashcli-bundle.json unreadable: {exc}")
        return gaps

    if not isinstance(data.get("python_dependencies"), dict):
        gaps.append(
            "flashcli-bundle.json missing python_dependencies "
            "(run: flashcli bundle build …)"
        )

    lib_dir = root / "lib"
    if not lib_dir.is_dir():
        gaps.append("missing lib/ directory")
    elif not any(lib_dir.glob("flash_rt_kernels*.so")):
        gaps.append("no lib/flash_rt_kernels*-sm*-cu*-py*.so")

    if lib_dir.is_dir() and not any(lib_dir.glob("flash_rt_fa2*.so")):
        gaps.append("no lib/flash_rt_fa2*.so (required for Qwen attention)")

    if lib_dir.is_dir() and not any(lib_dir.glob("flash_rt_fp4*.so")):
        gaps.append("no lib/flash_rt_fp4*.so (NVFP4 on SM120 — required for qwen_nvfp4)")

    stray = sorted(root.glob("flash_rt_*.so"))
    if stray:
        gaps.append(
            f"native .so must be under lib/, not bundle root: "
            f"{', '.join(p.name for p in stray[:3])}"
            + (" …" if len(stray) > 3 else "")
        )

    if not (root / "flash_rt").is_dir():
        gaps.append("missing flash_rt/ Python tree")

    for rel in ("run.py", "serve.py"):
        if not (root / rel).is_file():
            gaps.append(f"missing entry file {rel}")

    modules = data.get("modules")
    if isinstance(modules, list):
        for entry in modules:
            if not isinstance(entry, dict):
                continue
            file_rel = str(entry.get("file", "")).strip()
            if file_rel.endswith(".so") and not file_rel.startswith("lib/"):
                gaps.append(f"modules[].file must be under lib/: {file_rel!r}")

    return gaps


def format_bundle_not_ready_message(root: Path) -> str:
    root = root.resolve()
    gaps = describe_bundle_assembly_gaps(root)
    lines = [f"Bundle at {root} is not assembled yet.", "", "Missing or incomplete:"]
    lines.extend(f"  - {g}" for g in gaps)
    script = bundle_build_script(root)
    if script is not None:
        lines.extend(
            [
                "",
                "Build (native artifacts go to lib/):",
                f"  bash {script} --repo-root /path/to/FlashRT -j \"$(nproc)\"",
                f"  # or: bash {script} --repo-root /path/to/FlashRT --pack-only",
                f"  flashcli bundle validate {root}",
            ]
        )
    return "\n".join(lines)
