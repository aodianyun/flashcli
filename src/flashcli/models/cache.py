"""Model cache (re-export protocol + host checkpoint download)."""

from flashcli.bundle.weights import ensure_checkpoint as _host_ensure_checkpoint
from flashcli_bundle import cache as _cache


def ensure_model_cached(*args, **kwargs):
    if kwargs.get("download", True):
        kwargs["ensure_checkpoint_fn"] = _host_ensure_checkpoint
    return _cache.ensure_model_cached(*args, **kwargs)


is_cached = _cache.is_cached
preset_cache_dir = _cache.preset_cache_dir

__all__ = ["ensure_model_cached", "is_cached", "preset_cache_dir"]
