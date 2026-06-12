"""Load FlashRT ``serving/qwen36_agent`` (required for qwen36 — no legacy OpenAI server)."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

_QWEN36_AGENT_PKG = "flash_rt.serve.qwen36_agent"
_QWEN36_AGENT_DEV_PKG = "qwen36_agent"


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


def _bundle_qwen36_agent_dir() -> Path | None:
    from flashcli_bundle.context import active_bundle

    bundle = active_bundle()
    if bundle is None:
        return None
    path = bundle.bundle_root / "flash_rt" / "serve" / "qwen36_agent"
    return path if path.is_dir() and (path / "__init__.py").is_file() else None


def _flashrt_qwen36_agent_dir() -> Path | None:
    for root in _flashrt_repo_roots():
        path = root / "serving" / "qwen36_agent"
        if path.is_dir() and (path / "__init__.py").is_file():
            return path
    return None


def _ensure_qwen36_agent_importable() -> str:
    try:
        importlib.import_module(f"{_QWEN36_AGENT_PKG}.service")
        return _QWEN36_AGENT_PKG
    except ImportError:
        pass

    agent_dir = _flashrt_qwen36_agent_dir()
    if agent_dir is not None:
        serving_root = str(agent_dir.parent)
        if serving_root not in sys.path:
            sys.path.insert(0, serving_root)
        importlib.import_module(f"{_QWEN36_AGENT_DEV_PKG}.service")
        return _QWEN36_AGENT_DEV_PKG

    bundled = _bundle_qwen36_agent_dir()
    if bundled is not None:
        try:
            importlib.import_module(f"{_QWEN36_AGENT_PKG}.service")
            return _QWEN36_AGENT_PKG
        except ImportError as exc:
            raise ImportError(
                f"Found staged {bundled} but cannot import {_QWEN36_AGENT_PKG}: {exc}"
            ) from exc

    raise ImportError(
        "Cannot import FlashRT qwen36_agent. Rebuild the bundle:\n"
        "  bash scripts/release_bundle.sh --bundle qwen_nvfp4\n"
        "Stages flash_rt/serve/qwen36_agent/ from FlashRT/serving/qwen36_agent/\n"
        "For local dev, set FLASHRT_REPO_ROOT to a FlashRT tree with serving/qwen36_agent/."
    )


def import_qwen36_agent_modules() -> dict[str, Any]:
    prefix = _ensure_qwen36_agent_importable()
    service_mod = importlib.import_module(f"{prefix}.service")
    engine_mod = importlib.import_module(f"{prefix}.qwen36_engine")
    return {
        "AgentService": service_mod.AgentService,
        "AgentRequest": service_mod.AgentRequest,
        "AgentResult": service_mod.AgentResult,
        "request_from_openai": service_mod.request_from_openai,
        "result_to_openai": service_mod.result_to_openai,
        "Qwen36FrontendAgentEngine": engine_mod.Qwen36FrontendAgentEngine,
    }
