#!/usr/bin/env python3
"""Write build-time manifest overlay (read-only author ``flashcli-bundle.json``).

See docs/bundle_manifest_policy.md — publishers maintain ``flashcli-bundle.json``;
this script only writes ``--output-json`` (typically ``.build/manifest-overlay.json``).
"""

from __future__ import annotations

import argparse
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
        import tomli

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


def extract_runtime_packages(repo_root: Path) -> tuple[str, list[str]]:
    merged: list[str] = []
    req_file = _runtime_requirements_file(repo_root)
    if req_file.is_file():
        merged.extend(_parse_requirements_txt(req_file.read_text(encoding="utf-8")))
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        data = _load_toml(pyproject)
        project = data.get("project", {})
        optional = project.get("optional-dependencies", {})
        merged.extend(project.get("dependencies", []))
        merged.extend(optional.get("torch", []))
    elif not merged:
        raise FileNotFoundError(f"No runtime requirements under {repo_root}")

    merged = _dedupe(merged)
    torch_spec = "torch"
    pip_packages: list[str] = []
    for spec in merged:
        if _req_name(spec) in _TORCH_NAMES:
            torch_spec = spec
        else:
            pip_packages.append(spec)

    present = {_req_name(p) for p in pip_packages}
    missing_required = sorted(_REQUIRED_PIP - present)
    if missing_required:
        raise SystemExit(
            f"Required runtime packages missing from merged spec: {missing_required}"
        )
    return torch_spec, pip_packages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(os.environ.get("REPO_ROOT", ".")))
    parser.add_argument("--bundle-json", type=Path, required=True)
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
    parser.add_argument("--git-ref", default="main")
    parser.add_argument(
        "--python-minor",
        required=True,
        help="Single Python ABI for this bundle release: 310, 311, 312",
    )
    parser.add_argument(
        "--matrix-manifest",
        action="store_true",
        help="Scan lib/ and emit runtime/ directory map",
    )
    parser.add_argument(
        "--native-artifact-tag",
        default="",
        help="Tag suffix for this build cell (informational; lib/ scan drives runtime map)",
    )
    parser.add_argument(
        "--base-artifact",
        default="base.tar.gz",
        help="Relative path for base artifact in FlashHub repo",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="Write generated overlay here (.build/manifest-overlay.json); never overwrite --bundle-json",
    )
    parser.add_argument(
        "--full-manifest",
        action="store_true",
        help="Write merged full manifest to --output-json (dist/ only; not bundle source)",
    )
    parser.add_argument(
        "--sync-python-dependencies",
        action="store_true",
        help="Deprecated: overwrite python_dependencies from FlashRT runtime-inference.txt",
    )
    args = parser.parse_args()

    lib_dir = args.lib_dir.resolve()
    bundle_path = args.bundle_json.resolve()
    repo_root = args.repo_root.resolve()
    output_path = args.output_json.resolve()

    _scripts_lib = Path(__file__).resolve().parent / "lib"
    if str(_scripts_lib) not in sys.path:
        sys.path.insert(0, str(_scripts_lib))
    from flashcli_bundle_path import ensure_flashcli_bundle_on_path

    ensure_flashcli_bundle_on_path(Path(__file__).resolve().parents[1])

    py_minor = str(args.python_minor).strip()
    if not py_minor.isdigit() or len(py_minor) != 3:
        raise SystemExit(f"--python-minor must be 310/311/312, got {py_minor!r}")

    runtime_artifacts: dict[str, str] = {}

    if args.matrix_manifest:
        from flashcli_bundle.native_naming import parse_native_tag_from_filename

        flat_sos = sorted(lib_dir.glob("*.so"))
        if flat_sos:
            for so in flat_sos:
                parsed = parse_native_tag_from_filename(so.name)
                if parsed is None:
                    continue
                cell = parsed.catalog_key()
                if parsed.python_minor != py_minor:
                    continue
                if cell not in runtime_artifacts:
                    runtime_artifacts[cell] = f"runtime/{cell}"
        else:
            for cell_dir in sorted(lib_dir.iterdir()):
                if not cell_dir.is_dir():
                    continue
                cell_sos = sorted(cell_dir.glob("*.so"))
                if not cell_sos:
                    continue
                cell_name = cell_dir.name
                runtime_artifacts[cell_name] = f"runtime/{cell_name}"

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    author_deps = bundle.get("python_dependencies")
    if args.sync_python_dependencies:
        torch_spec, pip_packages = extract_runtime_packages(repo_root)
        author_deps = {
            "torch": {"package": torch_spec, "index": args.torch_index},
            "pip": pip_packages,
        }
    bundle["format"] = "flashcli-model-bundle"
    bundle["format_version"] = 3
    bundle.pop("runtime_dir", None)
    bundle.pop("native_runtime", None)
    bundle.pop("native_layout", None)
    bundle.pop("modules", None)
    bundle.pop("native_libs", None)
    bundle.pop("native", None)
    bundle.pop("native_matrix", None)
    bundle.pop("artifacts", None)
    bundle.pop("cuda", None)
    bundle.pop("requires", None)
    bundle.pop("capabilities", None)
    bundle.pop("python", None)

    bundle["python_abi"] = py_minor
    if author_deps is not None:
        bundle["python_dependencies"] = author_deps
    if runtime_artifacts:
        bundle["runtime"] = runtime_artifacts
    bundle["build"] = {
        "runtime_version": args.runtime_version,
        "flashrt_tag": args.flashrt_tag,
        "git_commit": args.git_commit,
        "git_ref": args.git_ref,
        "build_id": args.build_id,
        "target": {
            "sm": args.sm,
            "os": args.os_name,
            "arch": args.cpuarch,
            "gpu_arch_cmake": args.gpu_arch,
            "python_abi": py_minor,
        },
        "features": {
            "fa2": args.has_fa2 == "1",
            "nvfp4": args.has_fp4 == "1",
            "fmha": args.has_fmha == "1",
        },
    }
    if args.native_artifact_tag:
        bundle["build"]["native_artifact_tag"] = args.native_artifact_tag

    if args.full_manifest:
        payload = bundle
    else:
        payload = {
            "format_version": 3,
            "python_abi": py_minor,
            "build": bundle["build"],
        }
        if runtime_artifacts:
            payload["runtime"] = runtime_artifacts

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
