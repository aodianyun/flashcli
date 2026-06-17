"""Parse FlashHub preset refs (``namespace/bundle:version[@variant]``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from flashcli import config
from flashcli.models.registry import Preset

_REF_EXAMPLES = (
    "flashcli-bundle/pi05_libero:1.0.3\n"
    "  flashcli-bundle/qwen_nvfp4:1.0.1@qwen36\n"
    "  bundles/qwen_nvfp4@qwen36  (local dev)"
)

_SHORT_REF_RE = re.compile(r"^([^/]+)/([^:]+):([^@]+)$")
_CACHE_SEGMENT_RE = re.compile(r"[^\w.\-+]+")


@dataclass(frozen=True)
class PresetRef:
    ref: str
    repo_url: str
    variant: str | None
    cache_key: str
    local: bool = False


def _cache_segment(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("cache segment must not be empty")
    return _CACHE_SEGMENT_RE.sub("-", cleaned)


def cache_key_from_coordinates(
    bundle: str,
    version: str,
    variant: str | None = None,
) -> str:
    b = _cache_segment(bundle)
    v = _cache_segment(version)
    if variant:
        return f"{b}/{v}@{_cache_segment(variant)}"
    return f"{b}/{v}"


def _bundle_version_from_ref_body(body: str) -> tuple[str, str]:
    if body.startswith("http://") or body.startswith("https://"):
        path = urlparse(body.rstrip("/")).path.rstrip("/")
        for part in reversed(path.split("/")):
            if ":" in part:
                bundle, version = part.split(":", 1)
                if bundle.strip() and version.strip():
                    return bundle.strip(), version.strip()
        raise ValueError(f"Cannot parse bundle:version from URL path: {body!r}")
    match = _SHORT_REF_RE.match(body)
    if match:
        _namespace, bundle, version = match.groups()
        return bundle, version
    raise ValueError(f"Cannot parse bundle:version from ref body: {body!r}")


def cache_key(ref: str) -> str:
    body, variant = _split_variant(ref.strip())
    if body.startswith("local:"):
        bundle_name = body.split(":", 1)[1].strip()
        return cache_key_from_coordinates(bundle_name, "local", variant)
    try:
        bundle, version = _bundle_version_from_ref_body(body)
        return cache_key_from_coordinates(bundle, version, variant)
    except ValueError as exc:
        raise ValueError(
            f"Cannot derive cache path from ref {ref!r}: {exc}"
        ) from exc


def parse_bundle_path_arg(raw: str) -> tuple[str, str | None]:
    return _split_variant(raw)


def _split_variant(raw: str) -> tuple[str, str | None]:
    body = raw.strip()
    if not body:
        raise ValueError("Preset ref must not be empty")
    if "@" in body:
        repo_part, variant = body.rsplit("@", 1)
        variant = variant.strip()
        if not variant:
            raise ValueError(f"Invalid preset ref {raw!r}: empty variant after '@'")
        return repo_part.strip(), variant
    return body, None


def is_flashhub_ref(raw: str) -> bool:
    body, _ = _split_variant(raw)
    if body.startswith("http://") or body.startswith("https://"):
        return True
    return _SHORT_REF_RE.match(body) is not None


def resolve_bundle_root(path: Path) -> Path:
    raw = path.expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return (config.package_root() / raw).resolve()


def _is_bundle_root(path: Path) -> bool:
    from flashcli_bundle.layout import is_bundle_root

    return is_bundle_root(path)


def resolve_local_bundle_preset(root: Path, variant: str | None) -> Preset:
    root = root.expanduser().resolve()
    if not _is_bundle_root(root):
        raise ValueError(f"Not a bundle root: {root}")
    label = f"local:{root.name}"
    canonical = f"{label}@{variant}" if variant else label
    raw_cfg: dict = {"bundle": {"local_root": str(root)}}
    if variant:
        raw_cfg["bundle_variant"] = variant
    key = cache_key_from_coordinates(root.name, "local", variant)
    return Preset(name=canonical, raw=raw_cfg, cache_key=key)


def resolve_run_target(positional: str | None) -> tuple[Preset, Path | None]:
    if not positional:
        raise ValueError(
            "Usage: flashcli run REF[@variant]\n"
            f"Examples:\n  {_REF_EXAMPLES}"
        )
    path_str, variant = parse_bundle_path_arg(positional)
    local_root = resolve_bundle_root(Path(path_str))
    if _is_bundle_root(local_root):
        return resolve_local_bundle_preset(local_root, variant), local_root
    if is_flashhub_ref(path_str):
        return resolve_preset(positional), None
    raise ValueError(
        f"{positional!r} is not a local bundle root (missing flashcli-bundle.json) "
        f"and not a valid FlashHub ref.\n"
        f"Examples:\n  {_REF_EXAMPLES}"
    )


def _repo_url_from_body(body: str) -> str:
    if body.startswith("http://") or body.startswith("https://"):
        return body.rstrip("/")
    match = _SHORT_REF_RE.match(body)
    if not match:
        raise ValueError(
            f"Invalid preset ref {body!r}. Expected:\n"
            f"  namespace/bundle:version[@variant]\n"
            f"Examples:\n  {_REF_EXAMPLES}"
        )
    namespace, bundle, version = match.groups()
    base = config.FLASHHUB_API_BASE.rstrip("/")
    return f"{base}/{namespace}/{bundle}:{version}"


def parse_preset_ref(raw: str) -> PresetRef:
    body, variant = _split_variant(raw)
    repo_url = _repo_url_from_body(body)
    if body.startswith("http://") or body.startswith("https://"):
        canonical = body if variant is None else f"{body}@{variant}"
    else:
        canonical = body if variant is None else f"{body}@{variant}"
    return PresetRef(
        ref=canonical,
        repo_url=repo_url,
        variant=variant,
        cache_key=cache_key(canonical),
    )


def resolve_preset(raw: str) -> Preset:
    parsed = parse_preset_ref(raw)
    raw_cfg: dict = {"bundle": {"repo": parsed.repo_url}}
    if parsed.variant:
        raw_cfg["bundle_variant"] = parsed.variant
    return Preset(name=parsed.ref, raw=raw_cfg, cache_key=parsed.cache_key)


def preset_cache_key(preset: Preset) -> str:
    if preset.cache_key:
        return preset.cache_key
    return cache_key(preset.name)


def preset_cache_path(preset: Preset, *, root: Path | None = None) -> Path:
    base = root if root is not None else config.MODELS_DIR
    return base / preset_cache_key(preset)
