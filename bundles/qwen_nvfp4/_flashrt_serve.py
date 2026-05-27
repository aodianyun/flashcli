"""Load Qwen OpenAI server engines staged into the bundle runtime."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

_ENGINE_ATTR = {
    "qwen3": "Qwen3Engine",
    "qwen36": "Qwen36Engine",
}
_EXAMPLE_FILES = {
    "qwen3": "qwen3_openai_server.py",
    "qwen36": "qwen36_openai_server.py",
}
_STAGED_FILES = {
    "qwen3": "qwen3_openai.py",
    "qwen36": "qwen36_openai.py",
}


def _bundle_serve_py(variant: str) -> Path | None:
    from flashcli.bundle.activate import active_bundle
    from flashcli.bundle.manifest import bundle_format_version

    bundle = active_bundle()
    if bundle is None:
        return None
    if bundle_format_version(bundle) >= 2:
        path = bundle.bundle_root / "flash_rt" / "serve" / _STAGED_FILES[variant]
    else:
        path = (
            bundle.runtime_dir
            / "python"
            / "flash_rt"
            / "serve"
            / _STAGED_FILES[variant]
        )
    return path if path.is_file() else None


def _flashrt_examples_py(variant: str) -> Path | None:
    env_root = os.environ.get("FLASHRT_REPO_ROOT", "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root))
    try:
        from flashcli.bundle.activate import active_bundle

        bundle = active_bundle()
        if bundle is not None:
            candidates.append(
                (bundle.bundle_root / ".." / ".." / ".." / "FlashRT").resolve()
            )
            candidates.append(
                (bundle.bundle_root / ".." / ".." / ".." / ".." / "FlashRT").resolve()
            )
    except Exception:
        pass
    for root in candidates:
        path = root / "examples" / _EXAMPLE_FILES[variant]
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


def import_qwen_engine_class(variant: str) -> type[Any]:
    """Return ``Qwen3Engine`` or ``Qwen36Engine`` from staged or dev paths."""
    if variant not in _ENGINE_ATTR:
        raise ValueError(f"Unknown variant {variant!r}")

    attr = _ENGINE_ATTR[variant]
    mod_name = f"flash_rt.serve.{variant}_openai"

    try:
        mod = importlib.import_module(mod_name)
        return getattr(mod, attr)
    except ImportError:
        pass

    for path in (_bundle_serve_py(variant), _flashrt_examples_py(variant)):
        if path is None:
            continue
        mod = _load_module_from_path(path, f"_flashrt_serve_{variant}")
        return getattr(mod, attr)

    raise ImportError(
        f"Cannot import {attr}. Build the bundle first:\n"
        f"  bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT\n"
        f"(creates flash_rt/serve/{_STAGED_FILES[variant]})\n"
        f"For local dev, set FLASHRT_REPO_ROOT or ensure "
        f"examples/{_EXAMPLE_FILES[variant]} exists."
    )


def import_qwen3_engine_class() -> type[Any]:
    return import_qwen_engine_class("qwen3")


def import_qwen36_engine_class() -> type[Any]:
    return import_qwen_engine_class("qwen36")
