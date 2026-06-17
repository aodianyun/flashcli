"""Preset ref parsing for infer runtime (protocol re-export)."""

from flashcli_bundle import preset_ref as _pr

PresetRef = _pr.PresetRef
cache_key = _pr.cache_key
cache_key_from_coordinates = _pr.cache_key_from_coordinates
is_flashhub_ref = _pr.is_flashhub_ref
parse_bundle_path_arg = _pr.parse_bundle_path_arg
parse_preset_ref = _pr.parse_preset_ref
preset_cache_key = _pr.preset_cache_key
preset_cache_path = _pr.preset_cache_path
resolve_bundle_root = _pr.resolve_bundle_root
resolve_local_bundle_preset = _pr.resolve_local_bundle_preset
resolve_preset = _pr.resolve_preset
resolve_run_target = _pr.resolve_run_target

__all__ = [
    "PresetRef",
    "cache_key",
    "cache_key_from_coordinates",
    "is_flashhub_ref",
    "parse_bundle_path_arg",
    "parse_preset_ref",
    "preset_cache_key",
    "preset_cache_path",
    "resolve_bundle_root",
    "resolve_local_bundle_preset",
    "resolve_preset",
    "resolve_run_target",
]
