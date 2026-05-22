"""Resolve per-environment bundle sources from models.yaml."""

from __future__ import annotations

from typing import Any

from flashcli.models.registry import Preset
from flashcli.runtime.detect import GpuInfo, detect_gpu, detect_gpu_or_raise


def variant_dir_name(gpu: GpuInfo) -> str:
    return f"sm{gpu.sm}-cu{gpu.cuda_tag}-{gpu.os_name}-{gpu.arch}"


def _parse_variant_key(name: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse ``sm89-cu130-linux-x86_64`` into (sm, cuda_tag, os, arch)."""
    parts = name.split("-")
    sm = cuda = None
    os_name: str | None = None
    arch: str | None = None
    for part in parts:
        if part.startswith("sm") and len(part) > 2:
            sm = part[2:]
        elif part.startswith("cu") and len(part) > 2:
            cuda = part[2:]
    if len(parts) >= 4 and parts[-2] and parts[-1]:
        os_name = parts[-2]
        arch = parts[-1]
    return sm, cuda, os_name, arch


def _cuda_runtime_family(cuda_tag: str) -> str:
    """Group CUDA tags for fuzzy catalog match (12.x vs 13.x runtime)."""
    tag = cuda_tag.strip()
    if tag.startswith("13") or tag in ("130",):
        return "13"
    if tag.startswith("12") or tag in ("124", "128", "120"):
        return "12"
    return tag[:2] if len(tag) >= 2 else tag


def _score_variant_key(key: str, gpu: GpuInfo) -> int:
    sm, cuda, os_name, arch = _parse_variant_key(key)
    score = 0
    if sm == gpu.sm:
        score += 10
    if cuda and cuda == gpu.cuda_tag:
        score += 5
    elif cuda and _cuda_runtime_family(cuda) == _cuda_runtime_family(gpu.cuda_tag):
        score += 3
    if os_name and os_name == gpu.os_name:
        score += 2
    if arch and arch == gpu.arch:
        score += 2
    return score


def _pick_catalog_variant_key(variants: dict[str, Any], gpu: GpuInfo) -> str | None:
    """Exact env key first, then fuzzy match (same SM; CUDA 12.x↔12.x only, not 12→13)."""
    exact = variant_dir_name(gpu)
    if exact in variants:
        return exact

    host_family = _cuda_runtime_family(gpu.cuda_tag)
    candidates: list[tuple[int, str]] = []
    for key in variants:
        name = str(key).strip()
        if not name:
            continue
        _sm, cuda, _os, _arch = _parse_variant_key(name)
        if _sm != gpu.sm:
            continue
        if cuda and _cuda_runtime_family(cuda) != host_family:
            continue
        score = _score_variant_key(name, gpu)
        if score > 0:
            candidates.append((score, name))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][1]

# Keys copied from the parent ``bundle`` block into each catalog variant entry.
_SHARED_KEYS = frozenset({"refs", "versions", "variants_dir"})

# Source keys resolved per environment (not inherited from siblings).
_SOURCE_KEYS = frozenset({"zip", "path", "git", "ref"})


class BundleCatalogError(RuntimeError):
    """Invalid or missing bundle configuration in models.yaml."""


class BundleVariantNotFoundError(BundleCatalogError):
    """No catalog entry for the current machine environment."""

    def __init__(
        self,
        preset_name: str,
        *,
        wanted: str,
        available: list[str],
        gpu: GpuInfo | None = None,
    ) -> None:
        self.preset_name = preset_name
        self.wanted = wanted
        self.available = available
        self.gpu = gpu
        avail = ", ".join(available) if available else "(none)"
        gpu_line = ""
        if gpu is not None:
            gpu_line = (
                f"\n  Detected GPU: {gpu.gpu_name or 'NVIDIA GPU'} "
                f"(sm{gpu.sm}, cuda_tag={gpu.cuda_tag}, {gpu.os_name}-{gpu.arch})"
            )
        cuda_hint = ""
        if gpu is not None:
            fam = _cuda_runtime_family(gpu.cuda_tag)
            cuda_hint = (
                f"\n  Note: CUDA {fam}.x runtime on host (cuda_tag={gpu.cuda_tag}); "
                f"do not use a cu13x-built zip on cu12x without matching libcudart. "
                f"Add a {wanted} entry or install the bundle's CUDA runtime libraries."
            )
        super().__init__(
            f"No bundle configured in models.yaml for preset {preset_name!r} "
            f"and environment {wanted!r}.{gpu_line}{cuda_hint}\n"
            f"  Add under bundle.variants:\n"
            f"    {wanted}:\n"
            f"      zip: ...   # or path: / git:\n"
            f"  Configured environments: {avail}"
        )


def raw_bundle_cfg(preset: Preset) -> dict[str, Any]:
    raw = preset.raw.get("bundle") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def catalog_variant_keys(preset: Preset) -> list[str]:
    """Environment keys declared under ``bundle.variants`` in models.yaml."""
    raw = raw_bundle_cfg(preset).get("variants")
    if not isinstance(raw, dict):
        return []
    return sorted(str(k).strip() for k in raw if str(k).strip())


def has_catalog_variants(preset: Preset) -> bool:
    return bool(catalog_variant_keys(preset))


def _base_shared_cfg(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in raw.items()
        if k not in ("variants", *_SOURCE_KEYS)
    }


def _normalize_variant_entry(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        return dict(entry)
    if isinstance(entry, str):
        spec = entry.strip()
        if not spec:
            return {}
        if spec.endswith(".zip") or spec.startswith(("http://", "https://")):
            return {"zip": spec}
        return {"path": spec}
    return {}


def _resolve_variant_entry(
    variants: dict[str, Any],
    env_key: str,
    entry_raw: Any,
    *,
    _seen: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve a variant entry; string values may alias another variant key."""
    seen = _seen or set()
    if env_key in seen:
        raise BundleCatalogError(
            f"Preset bundle.variants: alias cycle involving {env_key!r}"
        )
    seen.add(env_key)

    if isinstance(entry_raw, str):
        alias = entry_raw.strip()
        if alias in variants and alias != env_key:
            return _resolve_variant_entry(
                variants, alias, variants[alias], _seen=seen
            )
        return _normalize_variant_entry(entry_raw)

    if entry_raw is None:
        return {}

    return _normalize_variant_entry(entry_raw)


def _merge_variant_cfg(raw: dict[str, Any], env_key: str, entry: dict[str, Any]) -> dict[str, Any]:
    merged = _base_shared_cfg(raw)
    merged.update({k: v for k, v in entry.items() if k not in ("variants",)})
    merged["catalog_variant"] = env_key
    return merged


def _legacy_effective_cfg(raw: dict[str, Any], *, env_key: str) -> dict[str, Any]:
    cfg = _base_shared_cfg(raw)
    for key in _SOURCE_KEYS:
        if key in raw:
            cfg[key] = raw[key]
    cfg["catalog_variant"] = env_key
    return cfg


def resolve_effective_bundle_cfg(
    preset: Preset,
    *,
    gpu: GpuInfo | None = None,
    require_gpu: bool = True,
) -> tuple[dict[str, Any], str]:
    """Return (effective bundle cfg, environment key ``sm*-cu*-os-arch``).

    When ``bundle.variants`` is set, pick an entry by exact ``variant_dir_name`` or
    fuzzy match (same SM / OS / arch; CUDA tag may differ, e.g. cu124 vs cu130).
    Otherwise the top-level ``zip`` / ``path`` /
    ``git`` is used for all environments; zip/git trees may still contain inner
    ``variants/`` for artifact-level selection.
    """
    raw = raw_bundle_cfg(preset)
    variants = raw.get("variants")
    if not isinstance(variants, dict) or not variants:
        if require_gpu:
            gpu = gpu or detect_gpu_or_raise()
            env_key = variant_dir_name(gpu)
        else:
            gpu = gpu or detect_gpu()
            env_key = variant_dir_name(gpu) if gpu else "unknown"
        return _legacy_effective_cfg(raw, env_key=env_key), env_key

    if gpu is None:
        if require_gpu:
            gpu = detect_gpu_or_raise()
        else:
            gpu = detect_gpu()
            if gpu is None:
                raise BundleCatalogError(
                    f"Preset {preset.name!r} uses bundle.variants in models.yaml; "
                    "an NVIDIA GPU is required to select the environment."
                )

    assert gpu is not None
    detected_env = variant_dir_name(gpu)
    matched_key = _pick_catalog_variant_key(variants, gpu)
    if matched_key is None:
        raise BundleVariantNotFoundError(
            preset.name,
            wanted=detected_env,
            available=catalog_variant_keys(preset),
            gpu=gpu,
        )

    entry_raw = variants[matched_key]
    entry = _resolve_variant_entry(variants, matched_key, entry_raw)
    if not any(entry.get(k) for k in _SOURCE_KEYS):
        raise BundleCatalogError(
            f"Preset {preset.name!r} bundle.variants[{matched_key!r}] must set "
            "one of: zip, path, git"
        )

    merged = _merge_variant_cfg(raw, matched_key, entry)
    merged["catalog_detected_env"] = detected_env
    return merged, matched_key


def effective_bundle_cfg_for_preset(
    preset: Preset,
    *,
    gpu: GpuInfo | None = None,
) -> dict[str, Any]:
    cfg, _ = resolve_effective_bundle_cfg(preset, gpu=gpu, require_gpu=has_catalog_variants(preset))
    return cfg
