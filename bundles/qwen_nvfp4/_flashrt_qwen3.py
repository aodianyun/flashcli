"""Load FlashRT Qwen3 OpenAI example engine from staged bundle or dev tree."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

_ENGINE_ATTR = "Qwen3Engine"
_EXAMPLE_FILE = "qwen3_openai_server.py"
_STAGED_FILE = "qwen3_openai.py"


def _bundle_serve_py() -> Path | None:
    from flashcli_bundle.context import active_bundle
    from flashcli_bundle.manifest import bundle_format_version

    bundle = active_bundle()
    if bundle is None:
        return None
    if bundle_format_version(bundle) >= 2:
        path = bundle.bundle_root / "flash_rt" / "serve" / _STAGED_FILE
    else:
        path = (
            bundle.runtime_dir / "python" / "flash_rt" / "serve" / _STAGED_FILE
        )
    return path if path.is_file() else None


def _flashrt_repo_roots() -> list[Path]:
    env_root = os.environ.get("FLASHRT_REPO_ROOT", "").strip()
    roots: list[Path] = []
    if env_root:
        roots.append(Path(env_root))
    try:
        from flashcli_bundle.context import active_bundle

        bundle = active_bundle()
        if bundle is not None:
            roots.append(
                (bundle.bundle_root / ".." / ".." / ".." / "FlashRT").resolve()
            )
            roots.append(
                (bundle.bundle_root / ".." / ".." / ".." / ".." / "FlashRT").resolve()
            )
    except Exception:
        pass
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def _flashrt_examples_py() -> Path | None:
    for root in _flashrt_repo_roots():
        path = root / "examples" / _EXAMPLE_FILE
        if path.is_file():
            return path
    return None


def _load_module_from_path(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def import_qwen3_engine_class() -> type[Any]:
    mod_name = "flash_rt.serve.qwen3_openai"
    try:
        mod = importlib.import_module(mod_name)
        return getattr(mod, _ENGINE_ATTR)
    except ImportError:
        pass

    for path in (_bundle_serve_py(), _flashrt_examples_py()):
        if path is None:
            continue
        mod = _load_module_from_path(path, "_flashrt_qwen3_dev")
        return getattr(mod, _ENGINE_ATTR)

    raise ImportError(
        f"Cannot import {_ENGINE_ATTR}. Build the bundle first:\n"
        f"  bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT\n"
        f"(creates flash_rt/serve/{_STAGED_FILE})\n"
        f"For local dev, set FLASHRT_REPO_ROOT or ensure examples/{_EXAMPLE_FILE} exists."
    )
