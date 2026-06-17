"""Unified HTTP serve layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flashcli_bundle.infer.engines.base import ServeEngine

__all__ = ["build_app"]


def __getattr__(name: str) -> Any:
    if name == "build_app":
        from flashcli_bundle.infer.serve.app import build_app

        return build_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_app(engine: ServeEngine) -> Any:
    from flashcli_bundle.infer.serve.app import build_app as _build_app

    return _build_app(engine)
