"""Backward-compatible re-exports — prefer direct imports from split modules."""

from __future__ import annotations

from _flashrt_qwen3 import import_qwen3_engine_class
from _flashrt_qwen36_agent import import_qwen36_agent_modules

__all__ = [
    "import_qwen3_engine_class",
    "import_qwen36_agent_modules",
]
