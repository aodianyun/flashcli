#!/usr/bin/env python3
"""Static import closure for vendored gr00t inference (bundle-local).

Walks gr00t/*.py from inference entry modules, collects third-party imports,
and emits pinned requirements using Isaac-GR00T pyproject.toml when available.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import deque
from pathlib import Path

BUNDLE_DIR = Path(__file__).resolve().parent
VENDOR_ROOT = BUNDLE_DIR / "gr00t"
LOCK_PATH = BUNDLE_DIR / "gr00t-inference-requirements.txt"
MANIFEST_PATH = BUNDLE_DIR / "flashcli-bundle.json"

# Inference entry modules (preprocess + FlashRT denormalize).
ENTRY_MODULES = (
    "gr00t.policy.gr00t_policy",
    "gr00t.model",
    "gr00t.model.gr00t_n1d7.gr00t_n1d7",
    "gr00t.data.embodiment_tags",
)

# Map import root -> PyPI distribution name.
IMPORT_TO_PIP: dict[str, str] = {
    "PIL": "pillow",
    "cv2": "opencv-python-headless",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "tree": "dm-tree",
    "msgpack_numpy": "msgpack-numpy",
    "git": "gitpython",
    "huggingface_hub": "huggingface-hub",
    "flash_attn": "flash-attn",
    "ml_dtypes": "ml_dtypes",
}

# tyro 0.9+ no longer depends on click; do not pin click via manifest.
TRANSITIVE_SPECS: dict[str, list[str]] = {}

# Always include (runtime hub access; not always a static import root).
ALWAYS_EXTRAS: list[str] = ["huggingface-hub"]

# Isaac pyproject deps to never add via merge (training / sim / deployment).
ISAAC_SKIP: frozenset[str] = frozenset(
    {
        "datasets",
        "lmdb",
        "gymnasium",
        "matplotlib",
        "wandb",
        "deepspeed",
        "flash-attn",
        "pyzmq",
        "onnx",
        "onnxscript",
        "tensorrt-cu12",
        "tensorrt-cu13",
        "tensorrt-cu12-libs",
        "tensorrt-cu13-libs",
        "triton",
    }
)

# Never install via bundle manifest (training / sim / deployment / provided elsewhere).
DENYLIST_PIP: frozenset[str] = frozenset(
    set(ISAAC_SKIP)
    | {
        "torch",
        "torchvision",
        "torchaudio",
        "transformers",
        "torchcodec",
    }
)

# Already declared elsewhere in flashcli-bundle.json (torch stack + base pip).
MANIFEST_BASE_PIP: frozenset[str] = frozenset(
    {
        "numpy",
        "pyyaml",
        "safetensors",
        "sentencepiece",
        "ml_dtypes",
        "transformers",
        "pillow",
        "torchvision",
        "einops",
        "peft",
        "diffusers",
        "omegaconf",
        "pandas",
        "av",
        "scipy",
        "dm-tree",
        "opencv-python-headless",
    }
)


def _module_to_pip(root: str) -> str | None:
    if root in IMPORT_TO_PIP:
        return IMPORT_TO_PIP[root]
    if root.startswith("gr00t"):
        return None
    if root in sys.stdlib_module_names:
        return None
    # Heuristic: top-level name is usually the PyPI distribution.
    return root.replace("_", "-") if "_" in root else root


def _gr00t_py_path(module: str) -> Path | None:
    if not module.startswith("gr00t."):
        return None
    rel = module[len("gr00t.") :].replace(".", "/")
    path = VENDOR_ROOT / f"{rel}.py"
    if path.is_file():
        return path
    init = VENDOR_ROOT / rel / "__init__.py"
    if init.is_file():
        return init
    return None


def _enclosing_package(module: str, path: Path) -> str:
    if path.name == "__init__.py":
        return module
    parts = module.split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else module


def _resolve_internal(module: str, *, current: str, path: Path) -> str | None:
    if module.startswith("gr00t."):
        return module
    if not module.startswith("."):
        return None
    level = len(module) - len(module.lstrip("."))
    rel = module.lstrip(".")
    enclosing = _enclosing_package(current, path).split(".")
    if level > 1:
        enclosing = enclosing[: max(0, len(enclosing) - (level - 1))]
    if rel:
        return ".".join(enclosing + rel.split("."))
    return ".".join(enclosing) if enclosing else None


def _imports_in_file(path: Path, *, current_module: str) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    internal: set[str] = set()
    external: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name.startswith("gr00t"):
                    internal.add(alias.name)
                else:
                    external.add(root)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                resolved = _resolve_internal(
                    "." * node.level + mod,
                    current=current_module,
                    path=path,
                )
                if resolved and resolved.startswith("gr00t"):
                    internal.add(resolved)
                continue
            if mod.startswith("gr00t"):
                internal.add(mod)
                continue
            if mod:
                external.add(mod.split(".")[0])
    return internal, external


def _module_name_for_path(path: Path) -> str:
    rel = path.relative_to(VENDOR_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return "gr00t." + ".".join(parts)


def collect_closure() -> tuple[set[str], set[str]]:
    internal_seen: set[str] = set()
    external_roots: set[str] = set()
    queue: deque[str] = deque(ENTRY_MODULES)

    while queue:
        mod = queue.popleft()
        if mod in internal_seen:
            continue
        internal_seen.add(mod)
        path = _gr00t_py_path(mod)
        if path is None:
            continue
        current = _module_name_for_path(path)
        internal, external = _imports_in_file(path, current_module=current)
        external_roots.update(external)
        for child in sorted(internal):
            if child not in internal_seen:
                queue.append(child)

    pip_names: set[str] = set()
    for root in sorted(external_roots):
        pip = _module_to_pip(root)
        if pip and pip not in DENYLIST_PIP:
            pip_names.add(pip)
    return pip_names, external_roots


def _isaac_pyproject_path() -> Path | None:
    vendor_meta = VENDOR_ROOT / "VENDOR.json"
    if not vendor_meta.is_file():
        return None
    import json

    meta = json.loads(vendor_meta.read_text(encoding="utf-8"))
    ref = str(meta.get("git_ref", "")).strip()
    if not ref:
        return None
    safe_ref = re.sub(r"[^A-Za-z0-9._-]+", "_", ref)
    cache = Path.home() / ".flashcli" / "cache" / "isaac-gr00t-src" / safe_ref / "pyproject.toml"
    if cache.is_file():
        return cache
    return None


def _pins_from_pyproject(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    in_deps = False
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("dependencies = ["):
            in_deps = True
            continue
        if in_deps:
            if line.startswith("]"):
                break
            if not line.startswith('"'):
                continue
            spec = line.strip('",')
            if ";" in spec:
                spec = spec.split(";", 1)[0].strip()
            name = re.split(r"[<>=! \[]", spec, maxsplit=1)[0].strip().lower()
            if name:
                pins[name] = spec
    return pins


def _normalize_pip_name(name: str) -> str:
    return name.lower().replace("_", "-")


def _pin_for_name(name: str, pins: dict[str, str]) -> str:
    norm = _normalize_pip_name(name)
    if norm in pins:
        return pins[norm]
    return name


def _merge_specs(scan_pip: set[str], pins: dict[str, str]) -> list[str]:
    base = {_normalize_pip_name(x) for x in MANIFEST_BASE_PIP}
    deny = {_normalize_pip_name(x) for x in DENYLIST_PIP}
    merged: dict[str, str] = {}
    candidates = set(scan_pip)
    for extra in ALWAYS_EXTRAS:
        candidates.add(extra)
    for name in sorted(candidates):
        norm = _normalize_pip_name(name)
        if norm in base or norm in deny:
            continue
        merged[norm] = _pin_for_name(name, pins)
        for extra in TRANSITIVE_SPECS.get(norm, []):
            extra_name = _normalize_pip_name(re.split(r"[<>=! \[]", extra, maxsplit=1)[0])
            if extra_name not in base and extra_name not in deny:
                merged[extra_name] = extra
    return [merged[k] for k in sorted(merged)]


def _format_lock_lines(specs: list[str]) -> list[str]:
    lines: list[str] = [
        "# Auto-generated by _scan_gr00t_inference_imports.py — do not hand-edit.",
        "# Re-run: python3 bundles/groot_n17/_scan_gr00t_inference_imports.py",
        "# Sync into flashcli-bundle.json python_dependencies.pip (extras only).",
        "",
    ]
    lines.extend(specs)
    return lines


def _spec_name(spec: str) -> str:
    return _normalize_pip_name(re.split(r"[<>=! \[]", spec, maxsplit=1)[0])


def _check_manifest(specs: list[str]) -> int:
    if not MANIFEST_PATH.is_file():
        print(f"Missing {MANIFEST_PATH}", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pip = manifest.get("python_dependencies", {}).get("pip", [])
    joined = " ".join(str(p) for p in pip)
    missing: list[str] = []
    for spec in specs:
        name = _spec_name(spec)
        if name not in joined:
            missing.append(spec)
    if missing:
        print("flashcli-bundle.json pip missing lock-file extras:", file=sys.stderr)
        for spec in missing:
            print(f"  {spec}", file=sys.stderr)
        return 1
    print("flashcli-bundle.json pip matches gr00t-inference-requirements.txt extras")
    return 0


def main() -> int:
    if not VENDOR_ROOT.is_dir():
        print(f"Missing {VENDOR_ROOT}; run vendor_gr00t.sh first", file=sys.stderr)
        return 1

    pip_names, external_roots = collect_closure()
    pyproject = _isaac_pyproject_path()
    pins = _pins_from_pyproject(pyproject) if pyproject else {}
    specs = _merge_specs(pip_names, pins)
    if "--check-manifest" in sys.argv:
        return _check_manifest(specs)
    lines = _format_lock_lines(specs)
    LOCK_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Scanned entry modules: {', '.join(ENTRY_MODULES)}")
    print(f"External import roots ({len(external_roots)}): {', '.join(sorted(external_roots))}")
    print(f"Extra pip packages for manifest ({len(specs)}):")
    for line in specs:
        print(f"  {line}")
    print(f"Wrote {LOCK_PATH}")
    if pyproject:
        print(f"Pins from {pyproject}")
    else:
        print("WARN: Isaac pyproject.toml not found in cache; unpinned names only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
