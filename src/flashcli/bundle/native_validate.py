"""Native runtime validation (host: full Python discovery for ABI probe)."""

from flashcli_bundle.native_validate import (
    probe_native_so_abi,
    validate_native_runtime as _validate_native_runtime,
    validate_native_runtime_abi as _validate_native_runtime_abi,
    validate_native_runtime_matrix,
)

from flashcli.bundle.python_resolve import resolve_python_for_minor

__all__ = [
    "probe_native_so_abi",
    "resolve_python_for_minor",
    "validate_native_runtime",
    "validate_native_runtime_abi",
    "validate_native_runtime_matrix",
]


def validate_native_runtime(*args, **kwargs):
    kwargs.setdefault("python_for_minor", resolve_python_for_minor)
    return _validate_native_runtime(*args, **kwargs)


def validate_native_runtime_abi(bundle, **kwargs):
    kwargs.setdefault("python_for_minor", resolve_python_for_minor)
    return _validate_native_runtime_abi(bundle, **kwargs)
