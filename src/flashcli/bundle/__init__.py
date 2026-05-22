"""Model bundle loading and runtime activation."""

from flashcli.bundle.activate import activate_bundle, active_bundle
from flashcli.bundle.catalog import BundleCatalogError, BundleVariantNotFoundError
from flashcli.bundle.manifest import BundleManifest, load_bundle_manifest, validate_bundle_layout
from flashcli.bundle.git import ensure_bundle_from_git, is_bundle_cached
from flashcli.bundle.resolve import load_preset_bundle, resolve_bundle_root
from flashcli.bundle.weights import ensure_checkpoint, weights_spec
from flashcli.bundle.zip import ensure_bundle_from_zip, is_preset_bundle_cached

__all__ = [
    "BundleCatalogError",
    "BundleVariantNotFoundError",
    "BundleManifest",
    "activate_bundle",
    "active_bundle",
    "ensure_bundle_from_git",
    "ensure_bundle_from_zip",
    "is_bundle_cached",
    "is_preset_bundle_cached",
    "load_bundle_manifest",
    "load_preset_bundle",
    "resolve_bundle_root",
    "validate_bundle_layout",
    "ensure_checkpoint",
    "weights_spec",
]
