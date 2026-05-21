"""Fetch and extract model bundles from zip archives (URL or local path)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flashcli import config
from flashcli.bundle.git import (
    _write_marker,
    bundle_preset_cache,
    find_bundle_root_in_clone,
    read_bundle_marker,
    variant_dir_name,
)
from flashcli.bundle.manifest import load_bundle_manifest
from flashcli.bundle.ref import is_bundle_root
from flashcli.models.registry import Preset
from flashcli.runtime.detect import GpuInfo, detect_gpu_or_raise


def _bundle_cfg(preset: Preset) -> dict[str, Any]:
    raw = preset.raw.get("bundle") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def zip_spec(preset: Preset) -> str | None:
    """``bundle.zip`` value from models.yaml (URL or path)."""
    cfg = _bundle_cfg(preset)
    raw = cfg.get("zip")
    if isinstance(raw, str):
        spec = raw.strip()
        return spec or None
    return None


def _flashcli_root() -> Path:
    return config.MODELS_YAML.resolve().parent.parent


def resolve_zip_spec(spec: str) -> str:
    """Normalize local paths; leave http(s) URLs unchanged."""
    spec = spec.strip()
    parsed = urlparse(spec)
    if parsed.scheme in ("http", "https"):
        return spec
    raw = Path(spec).expanduser()
    if raw.is_absolute():
        return str(raw.resolve())
    return str((_flashcli_root() / raw).resolve())


def zip_cache_key(spec: str) -> str:
    return hashlib.sha256(resolve_zip_spec(spec).encode()).hexdigest()[:16]


def zip_work_dir(preset_name: str, spec: str) -> Path:
    return bundle_preset_cache(preset_name) / "zip" / zip_cache_key(spec)


def _marker_zip_spec(marker: dict[str, Any]) -> str:
    zip_block = marker.get("zip")
    if isinstance(zip_block, str):
        return zip_block.strip()
    if isinstance(zip_block, dict):
        return str(zip_block.get("spec") or zip_block.get("url") or "").strip()
    return str(marker.get("zip_spec") or "").strip()


def is_zip_bundle_cached(preset_name: str, spec: str) -> bool:
    resolved = resolve_zip_spec(spec)
    marker = read_bundle_marker(preset_name)
    if not marker:
        return False
    if marker.get("source") != "zip":
        return False
    if _marker_zip_spec(marker) != resolved:
        return False
    root = Path(str(marker.get("bundle_root", ""))).expanduser()
    return root.is_dir() and is_bundle_root(root)


def find_bundle_root_in_extracted(
    extract_root: Path,
    preset: Preset,
    gpu: GpuInfo | None,
) -> Path:
    """Locate ``flashcli-bundle.json`` after extracting a zip."""
    if is_bundle_root(extract_root):
        return extract_root.resolve()

    variants_root = extract_root / "variants"
    if variants_root.is_dir():
        if gpu is None:
            gpu = detect_gpu_or_raise()
        return find_bundle_root_in_clone(extract_root, preset, gpu)

    children = [
        p
        for p in extract_root.iterdir()
        if p.is_dir() and p.name not in ("__MACOSX",)
    ]
    if len(children) == 1 and is_bundle_root(children[0]):
        return children[0].resolve()

    for path in sorted(extract_root.rglob("flashcli-bundle.json")):
        root = path.parent
        if is_bundle_root(root):
            return root.resolve()

    raise FileNotFoundError(
        f"No flashcli-bundle.json under extracted zip at {extract_root}"
    )


def _safe_extract(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest) + os.sep):
                raise RuntimeError(f"Unsafe zip entry path: {member!r}")
        zf.extractall(dest)


def _download_zip(url: str, dest: Path, *, quiet: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return
    if not quiet:
        print(f"Downloading bundle zip ...")
    req = urllib.request.Request(  # noqa: S310
        url,
        headers={"User-Agent": f"flashcli/{config.__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, dest.open("wb") as out:
            shutil.copyfileobj(resp, out, length=1024 * 1024)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download bundle zip: {exc}") from exc


def _prepare_zip_archive(spec: str, work: Path, *, quiet: bool) -> Path:
    archive = work / "archive.zip"
    resolved = resolve_zip_spec(spec)
    parsed = urlparse(resolved)
    if parsed.scheme in ("http", "https"):
        _download_zip(resolved, archive, quiet=quiet)
        return archive
    local = Path(resolved)
    if not local.is_file():
        raise FileNotFoundError(f"Bundle zip not found: {local}")
    if local.resolve() != archive.resolve():
        if archive.is_file():
            archive.unlink()
        shutil.copy2(local, archive)
    return archive


def ensure_bundle_from_zip(
    preset: Preset,
    *,
    force: bool = False,
    quiet: bool = False,
) -> Path:
    """Download/extract ``bundle.zip`` and return the bundle root for this machine."""
    spec = zip_spec(preset)
    if spec is None:
        raise ValueError(
            f"Preset {preset.name!r} has no bundle.zip in models.yaml"
        )

    resolved = resolve_zip_spec(spec)
    if not force and is_zip_bundle_cached(preset.name, spec):
        marker = read_bundle_marker(preset.name)
        assert marker is not None
        root = Path(str(marker["bundle_root"])).resolve()
        if is_bundle_root(root):
            return root

    if os.environ.get("FLASHCLI_SKIP_BUNDLE_ZIP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        raise RuntimeError(
            "Bundle zip fetch disabled (FLASHCLI_SKIP_BUNDLE_ZIP=1) "
            f"and no cached bundle for {preset.name!r}"
        )

    work = zip_work_dir(preset.name, spec)
    extract_dir = work / "extracted"
    if force and extract_dir.is_dir():
        shutil.rmtree(extract_dir)

    archive = _prepare_zip_archive(spec, work, quiet=quiet)
    if not extract_dir.is_dir() or not any(extract_dir.iterdir()):
        if extract_dir.is_dir():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        if not quiet:
            print(f"Extracting bundle zip -> {extract_dir} ...")
        _safe_extract(archive, extract_dir)

    gpu = detect_gpu_or_raise()
    bundle_root = find_bundle_root_in_extracted(extract_dir, preset, gpu)

    _write_marker(
        preset.name,
        bundle_root=bundle_root,
        variant=variant_dir_name(gpu),
        git_ref=f"zip:{zip_cache_key(spec)}",
        repo=resolved,
        commit=zip_cache_key(spec),
    )
    marker_path = bundle_preset_cache(preset.name) / ".flashcli_bundle.json"
    if marker_path.is_file():
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        data["source"] = "zip"
        data["zip"] = resolved
        data.pop("git", None)
        marker_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    if not quiet:
        print(
            f"Bundle ready: {bundle_root} "
            f"(zip {resolved[:72]}{'...' if len(resolved) > 72 else ''}, "
            f"{variant_dir_name(gpu)})"
        )

    load_bundle_manifest(bundle_root)
    return bundle_root


def resolve_cached_zip_bundle_root(preset: Preset) -> Path | None:
    spec = zip_spec(preset)
    if spec is None:
        return None
    if not is_zip_bundle_cached(preset.name, spec):
        return None
    marker = read_bundle_marker(preset.name)
    if marker is None:
        return None
    root = Path(str(marker.get("bundle_root", ""))).expanduser()
    if is_bundle_root(root):
        return root.resolve()
    return None


def is_preset_bundle_cached(
    preset: Preset,
    *,
    git_ref: str | None = None,
) -> bool:
    """True when the catalog bundle source is present in the local cache."""
    spec = zip_spec(preset)
    if spec is not None:
        return is_zip_bundle_cached(preset.name, spec)
    from flashcli.bundle.ref import resolve_requested_git_ref

    want_ref = resolve_requested_git_ref(preset, git_ref)
    return is_bundle_cached(preset.name, git_ref=want_ref)
