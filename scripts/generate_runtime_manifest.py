#!/usr/bin/env python3
"""Generate runtime manifest.json + requirements-runtime.txt (no flashcli install needed)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

_TORCH_NAMES = frozenset({"torch", "pytorch"})
_REQUIRED_PIP = frozenset({"ml_dtypes", "numpy", "safetensors", "sentencepiece", "transformers"})


def _load_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        try:
            import tomli
        except ImportError as exc:
            raise SystemExit(
                "tomllib (3.11+) or tomli required to read pyproject.toml"
            ) from exc
        return tomli.loads(text)


def _req_name(spec: str) -> str:
    return re.split(r"[<>=!~;\s]", spec.strip(), maxsplit=1)[0].lower()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = _req_name(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _parse_requirements_txt(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _runtime_requirements_file(repo_root: Path) -> Path:
    return repo_root / "requirements" / "runtime-inference.txt"


def extract_runtime_packages(repo_root: Path) -> tuple[str, list[str], dict[str, list[str]]]:
    """Merge requirements/runtime-inference.txt + pyproject.toml [torch] extra."""
    merged: list[str] = []

    req_file = _runtime_requirements_file(repo_root)
    if req_file.is_file():
        merged.extend(_parse_requirements_txt(req_file.read_text(encoding="utf-8")))
    else:
        print(f"Warning: {req_file} missing; falling back to pyproject.toml only", file=sys.stderr)

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        data = _load_toml(pyproject)
        project = data.get("project", {})
        optional = project.get("optional-dependencies", {})
        merged.extend(project.get("dependencies", []))
        merged.extend(optional.get("torch", []))
    elif not merged:
        raise FileNotFoundError(f"No {req_file} and no pyproject.toml under {repo_root}")

    merged = _dedupe(merged)
    torch_spec = "torch"
    pip_packages: list[str] = []
    for spec in merged:
        if _req_name(spec) in _TORCH_NAMES:
            torch_spec = spec
        else:
            pip_packages.append(spec)

    optional_groups: dict[str, list[str]] = {}
    if pyproject.is_file():
        data = _load_toml(pyproject)
        optional_groups = {
            "server": list(
                data.get("project", {})
                .get("optional-dependencies", {})
                .get("server", [])
            ),
        }

    present = {_req_name(p) for p in pip_packages}
    missing_required = sorted(_REQUIRED_PIP - present)
    if missing_required:
        raise SystemExit(
            f"Required runtime packages missing from merged spec: {missing_required}\n"
            f"Check {req_file} and {pyproject}"
        )

    return torch_spec, pip_packages, optional_groups


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(os.environ.get("REPO_ROOT", ".")))
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--lib-dir", type=Path, required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--flashrt-tag", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--sm", required=True)
    parser.add_argument("--os-name", required=True)
    parser.add_argument("--cpuarch", required=True)
    parser.add_argument("--gpu-arch", required=True)
    parser.add_argument("--cuda-tag", required=True)
    parser.add_argument("--toolkit", required=True)
    parser.add_argument("--torch-index", required=True)
    parser.add_argument("--min-driver", required=True)
    parser.add_argument("--has-fa2", choices=("0", "1"), required=True)
    parser.add_argument("--has-fp4", choices=("0", "1"), required=True)
    parser.add_argument("--has-fmha", choices=("0", "1"), required=True)
    args = parser.parse_args()

    stage = args.stage_root.resolve()
    lib_dir = args.lib_dir.resolve()
    repo_root = args.repo_root.resolve()

    torch_spec, pip_packages, optional_groups = extract_runtime_packages(repo_root)

    modules = []
    for so in sorted(lib_dir.glob("*.so")):
        optional = so.name in ("flash_rt_fp4.so", "libfmha_fp16_strided.so")
        modules.append(
            {
                "file": f"lib/{so.name}",
                "sha256": sha256_file(so),
                "optional": optional,
            }
        )

    manifest = {
        "format": "flashrt-runtime-manifest",
        "format_version": 1,
        "runtime_version": args.runtime_version,
        "flashrt_tag": args.flashrt_tag,
        "git_commit": args.git_commit,
        "build_id": args.build_id,
        "target": {
            "sm": args.sm,
            "os": args.os_name,
            "arch": args.cpuarch,
            "gpu_arch_cmake": args.gpu_arch,
        },
        "cuda": {
            "cuda_tag": args.cuda_tag,
            "build_toolkit": args.toolkit,
            "min_driver_version": args.min_driver,
            "min_cuda_runtime": args.toolkit,
            "recommended_torch_index": args.torch_index,
        },
        "python": ">=3.10,<3.13",
        "python_dependencies": {
            "torch": torch_spec,
            "pip": pip_packages,
            "optional_groups": optional_groups,
        },
        "layout": {"lib": "lib", "python": "python"},
        "modules": modules,
        "features": {
            "fa2": args.has_fa2 == "1",
            "nvfp4": args.has_fp4 == "1",
            "fmha": args.has_fmha == "1",
        },
    }

    req_lines = "\n".join(pip_packages) + ("\n" if pip_packages else "")
    (stage / "requirements-runtime.txt").write_text(req_lines, encoding="utf-8")
    (stage / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
