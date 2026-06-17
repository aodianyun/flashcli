"""Dynamic import of bundle entry points."""

from __future__ import annotations

import importlib
from typing import Any

from flashcli_bundle.manifest_ext import EntrySpec
from flashcli_bundle.infer.engines.base import RunEngine, ServeEngine, coerce_run_engine, coerce_serve_engine


def load_entry(spec: EntrySpec, *, kind: str) -> Any:
    try:
        mod = importlib.import_module(spec.module)
    except ImportError as exc:
        raise ImportError(
            f"Cannot import bundle entry {kind} module {spec.module!r}. "
            "Ensure the bundle runtime is activated (PYTHONPATH)."
        ) from exc
    obj = getattr(mod, spec.attr, None)
    if obj is None:
        raise AttributeError(
            f"Module {spec.module!r} has no attribute {spec.attr!r}"
        )
    return obj


def load_run_engine(spec: EntrySpec) -> RunEngine:
    obj = load_entry(spec, kind="run")
    if isinstance(obj, type):
        return coerce_run_engine(obj())
    if callable(obj):
        return coerce_run_engine(obj())
    return coerce_run_engine(obj)


def load_serve_engine(spec: EntrySpec) -> ServeEngine:
    obj = load_entry(spec, kind="serve")
    if isinstance(obj, type):
        return coerce_serve_engine(obj())
    if callable(obj):
        return coerce_serve_engine(obj())
    return coerce_serve_engine(obj)
