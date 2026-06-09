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

    runtime = data.get("runtime")
    if not isinstance(runtime, dict) or not runtime:
        gaps.append("flashcli-bundle.json missing runtime map")
    else:
        has_kernels = False
        for rel in runtime.values():
            native_dir = root / str(rel).strip().lstrip("/")
            if native_dir.is_dir() and any(native_dir.glob("flash_rt_kernels*.so")):
                has_kernels = True
            if native_dir.is_dir() and not any(native_dir.glob("flash_rt_fa2*.so")):
                gaps.append(
                    f"no flash_rt_fa2*.so under {str(rel).strip().lstrip('/')}/ "
                    "(required for FlashRT attention)"
                )
        if not has_kernels:
            gaps.append("no runtime/<env-key>/flash_rt_kernels*.so")

    stray = sorted(root.glob("flash_rt_*.so"))
    if stray:
        gaps.append(
            f"native .so must be under runtime/<env-key>/, not bundle root: "
            f"{', '.join(p.name for p in stray[:3])}"
            + (" …" if len(stray) > 3 else "")
        )

    lib_dir = root / "lib"
    if lib_dir.is_dir() and any(lib_dir.glob("*.so")):
        gaps.append(
            "lib/ contains .so files — use runtime/<env-key>/ only "
            "(run scripts/pack_bundle.sh or release_bundle.sh)"
        )

    if not (root / "flash_rt").is_dir():
        gaps.append("missing flash_rt/ Python tree")

    if not (root / "run.py").is_file():
        gaps.append("missing entry file run.py")
    entry = data.get("entry") or {}
    if isinstance(entry, dict) and entry.get("serve") and not (root / "serve.py").is_file():
        gaps.append("missing entry file serve.py")

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
                "Build (matrix stages to lib/, then pack to runtime/<env-key>/):",
                f"  bash {script} --repo-root /path/to/FlashRT -j \"$(nproc)\"",
                f"  bash scripts/pack_bundle.sh --bundle-dir {root.parent.name}/{root.name}",
                f"  flashcli bundle validate {root}",
            ]
        )
    return "\n".join(lines)
