"""Model cache (re-export from flashcli-bundle protocol; infer resolve-only)."""

from flashcli_bundle.cache import ensure_model_cached, is_cached, preset_cache_dir

__all__ = ["ensure_model_cached", "is_cached", "preset_cache_dir"]
