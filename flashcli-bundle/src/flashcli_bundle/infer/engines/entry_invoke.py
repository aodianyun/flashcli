"""Load bundle entry callables (engine protocol or script ``main``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flashcli_bundle.manifest import BundleManifest, EntryMode, EntrySpec, entry_mode_for_capability
from flashcli_bundle.infer.engines.loader import load_entry


def entry_mode(spec: EntrySpec | None) -> EntryMode:
    if spec is None:
        return "engine"
    return spec.mode


def entry_mode_for_manifest(
    bundle: BundleManifest,
    *,
    capability: str,
) -> EntryMode:
    return entry_mode_for_capability(bundle, capability)


def load_entry_callable(spec: EntrySpec, *, kind: str) -> Callable[..., Any]:
    obj = load_entry(spec, kind=kind)
    if not callable(obj):
        raise TypeError(
            f"Bundle entry {kind} attr {spec.attr!r} is not callable (got {type(obj)!r})"
        )
    return obj


def invoke_script_main(fn: Callable[..., Any], argv: list[str]) -> int:
    result = fn(argv)
    if result is None:
        return 0
    if isinstance(result, int):
        return result
    return 0
