"""Parse flashcli-model-bundle manifests (format_version 3)."""

from flashcli_bundle.manifest import (
    BUNDLE_FORMAT,
    BUNDLE_FORMAT_VERSION,
    BundleManifest,
    EntrySpec,
    bundle_format_version,
    bundle_python_abi,
    bundle_python_root,
    bundle_runtime_dir,
    bundle_runtime_map,
    bundle_runtime_matrix,
    load_bundle_manifest,
    load_bundle_manifest_data,
    require_v3,
)
from flashcli_bundle.manifest_ext import (
    bundle_active_native_dir,
    bundle_torch_index,
    check_bundle_python_abi,
    resolve_bundle_env_key,
    validate_bundle_layout as _validate_bundle_layout,
)

from flashcli.bundle.python_resolve import resolve_python_for_minor

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_FORMAT_VERSION",
    "BundleManifest",
    "EntrySpec",
    "bundle_active_native_dir",
    "bundle_format_version",
    "bundle_python_abi",
    "bundle_python_root",
    "bundle_runtime_dir",
    "bundle_runtime_map",
    "bundle_runtime_matrix",
    "bundle_torch_index",
    "check_bundle_python_abi",
    "load_bundle_manifest",
    "load_bundle_manifest_data",
    "require_v3",
    "resolve_bundle_env_key",
    "validate_bundle_layout",
]


def validate_bundle_layout(
    bundle: BundleManifest,
    *,
    probe_abi: bool = False,
    env_key: str | None = None,
) -> list[str]:
    return _validate_bundle_layout(
        bundle,
        probe_abi=probe_abi,
        env_key=env_key,
        python_for_minor=resolve_python_for_minor if probe_abi else None,
    )
