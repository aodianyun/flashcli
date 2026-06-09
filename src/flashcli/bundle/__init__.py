"""Model bundle loading and runtime activation."""

from flashcli.bundle.activate import activate_bundle, active_bundle
from flashcli.bundle.catalog import BundleCatalogError
from flashcli.bundle.manifest import BundleManifest, load_bundle_manifest, validate_bundle_layout
from flashcli.bundle.resolve import activate_for_preset, load_preset_bundle, resolve_bundle_root
from flashcli.bundle.weights import ensure_checkpoint, weights_spec

__all__ = [
    "BundleCatalogError",
    "BundleManifest",
    "activate_bundle",
    "activate_for_preset",
    "active_bundle",
    "ensure_checkpoint",
    "load_bundle_manifest",
    "load_preset_bundle",
    "resolve_bundle_root",
    "validate_bundle_layout",
    "weights_spec",
]
