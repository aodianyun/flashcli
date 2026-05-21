"""Fetch model bundles from git (one ref = one immutable runtime snapshot)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from flashcli import config
from flashcli.bundle.manifest import load_bundle_manifest
from flashcli.bundle.ref import (
    is_bundle_root,
    list_catalog_refs,
    read_bundle_git_ref,
    resolve_requested_git_ref,
    sanitize_git_ref,
    validate_ref_in_catalog,
)
from flashcli.models.registry import Preset
from flashcli.runtime.detect import GpuInfo, detect_gpu_or_raise

_MARKER = ".flashcli_bundle.json"


def _bundle_cfg(preset: Preset) -> dict[str, Any]:
    raw = preset.raw.get("bundle") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _git_cfg(preset: Preset) -> dict[str, Any] | None:
    cfg = _bundle_cfg(preset)
    git = cfg.get("git")
    if not isinstance(git, dict):
        return None
    repo = str(git.get("repo", "")).strip()
    if not repo:
        return None
    return git


def bundle_preset_cache(preset_name: str) -> Path:
    return config.BUNDLES_DIR / preset_name


def repo_clone_dir(preset_name: str, git_ref: str) -> Path:
    """One local clone per (preset, git_ref) so multiple refs can coexist."""
    return bundle_preset_cache(preset_name) / "refs" / sanitize_git_ref(git_ref)


def _marker_path(preset_name: str) -> Path:
    return bundle_preset_cache(preset_name) / _MARKER


def _marker_git_ref(marker: dict[str, Any]) -> str:
    return str(
        marker.get("git_ref") or marker.get("ref") or marker.get("version") or ""
    ).strip()


def read_bundle_marker(preset_name: str) -> dict[str, Any] | None:
    path = _marker_path(preset_name)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _write_marker(
    preset_name: str,
    *,
    bundle_root: Path,
    variant: str,
    git_ref: str,
    repo: str,
    commit: str,
) -> None:
    cache = bundle_preset_cache(preset_name)
    cache.mkdir(parents=True, exist_ok=True)
    doc = {
        "preset": preset_name,
        "bundle_root": str(bundle_root.resolve()),
        "variant": variant,
        "git_ref": git_ref,
        "git": {"repo": repo, "ref": git_ref, "commit": commit},
    }
    _marker_path(preset_name).write_text(
        json.dumps(doc, indent=2) + "\n",
        encoding="utf-8",
    )


def is_bundle_cached(
    preset_name: str,
    *,
    git_ref: str | None = None,
    # Legacy CLI/tests
    version: str | None = None,
) -> bool:
    ref = git_ref if git_ref is not None else version
    marker = read_bundle_marker(preset_name)
    if not marker:
        return False
    if ref is not None and _marker_git_ref(marker) != ref:
        return False
    root = Path(str(marker.get("bundle_root", ""))).expanduser()
    return root.is_dir() and is_bundle_root(root)


def variant_dir_name(gpu: GpuInfo) -> str:
    return f"sm{gpu.sm}-cu{gpu.cuda_tag}-{gpu.os_name}-{gpu.arch}"


def _parse_variant_name(name: str) -> tuple[str | None, str | None]:
    parts = name.split("-")
    sm = cuda = None
    for part in parts:
        if part.startswith("sm") and len(part) > 2:
            sm = part[2:]
        elif part.startswith("cu") and len(part) > 2:
            cuda = part[2:]
    return sm, cuda


def _bundle_allowed_sms(bundle_root: Path) -> set[str] | None:
    from flashcli.bundle.config import bundle_allowed_sms
    from flashcli.bundle.manifest import load_bundle_manifest

    try:
        manifest = load_bundle_manifest(bundle_root)
    except (FileNotFoundError, ValueError, OSError):
        return None
    return bundle_allowed_sms(manifest)


def find_bundle_root_in_clone(
    repo_root: Path,
    preset: Preset,
    gpu: GpuInfo,
) -> Path:
    """``variants/<env>/`` is the bundle root at this git ref (flat layout)."""
    cfg = _bundle_cfg(preset)
    variants_subdir = str(cfg.get("variants_dir", "variants")).strip() or "variants"
    variants_root = repo_root / variants_subdir

    if variants_root.is_dir():
        exact = variants_root / variant_dir_name(gpu)
        if is_bundle_root(exact):
            return exact.resolve()

        if exact.is_dir():
            for child in exact.iterdir():
                if child.is_dir() and is_bundle_root(child):
                    raise FileNotFoundError(
                        f"Legacy semver layout at {child}. "
                        "Use git ref as version: tag/branch = one snapshot with "
                        f"flat {exact.name}/flashcli-bundle.json "
                        "(see docs/model_bundle_standard.md)."
                    )

        candidates: list[tuple[int, Path]] = []
        for child in variants_root.iterdir():
            if not child.is_dir() or not is_bundle_root(child):
                continue
            sm, cuda = _parse_variant_name(child.name)
            allowed = _bundle_allowed_sms(child)
            score = 0
            if sm == gpu.sm:
                score += 10
            if cuda == gpu.cuda_tag:
                score += 5
            if allowed is not None and sm in allowed:
                score += 1
            candidates.append((score, child))

        if candidates:
            candidates.sort(key=lambda x: (-x[0], x[1].name))
            if candidates[0][0] > 0:
                return candidates[0][1].resolve()

        names = ", ".join(sorted(p.name for p in variants_root.iterdir() if p.is_dir()))
        raise FileNotFoundError(
            f"No bundle under {variants_root} for {variant_dir_name(gpu)}. "
            f"Available: {names or '(none)'}"
        )

    if is_bundle_root(repo_root):
        return repo_root.resolve()

    raise FileNotFoundError(
        f"Git checkout at {repo_root} has no bundle at "
        f"{variants_subdir}/<env>/flashcli-bundle.json"
    )


def _run_git(args: list[str], *, cwd: Path | None = None) -> str:
    if shutil.which("git") is None:
        raise RuntimeError("git is required to fetch model bundles; install git and retry")
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    return (result.stdout or "").strip()


def _git_head(repo_dir: Path) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def _sync_repo(repo_url: str, ref: str, dest: Path, *, quiet: bool) -> None:
    ref = ref or "main"
    if dest.exists() and (dest / ".git").is_dir():
        if not quiet:
            print(f"Updating bundle repo {repo_url} @ {ref} ...")
        _run_git(["fetch", "--depth", "1", "origin", ref], cwd=dest)
        _run_git(["checkout", "FETCH_HEAD"], cwd=dest)
        return

    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(f"Cloning bundle repo {repo_url} @ {ref} ...")
    _run_git(
        [
            "clone",
            "--depth",
            "1",
            "--branch",
            ref,
            repo_url,
            str(dest),
        ]
    )


def ensure_bundle_from_git(
    preset: Preset,
    *,
    git_ref: str | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
    force: bool = False,
    quiet: bool = False,
) -> Path:
    """Checkout ``git_ref`` and return bundle root for this GPU environment."""
    git = _git_cfg(preset)
    if git is None:
        raise ValueError(
            f"Preset {preset.name!r} has no bundle.git.repo in models.yaml"
        )

    override = git_ref or bundle_ref or bundle_version
    requested_ref = resolve_requested_git_ref(preset, override)
    validate_ref_in_catalog(preset, requested_ref)

    if not force and is_bundle_cached(preset.name, git_ref=requested_ref):
        marker = read_bundle_marker(preset.name)
        assert marker is not None
        root = Path(str(marker["bundle_root"])).resolve()
        if is_bundle_root(root):
            return root

    if os.environ.get("FLASHCLI_SKIP_BUNDLE_GIT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        raise RuntimeError(
            "Bundle git fetch disabled (FLASHCLI_SKIP_BUNDLE_GIT=1) "
            f"and no cached bundle for {preset.name!r} @ {requested_ref!r}"
        )

    gpu = detect_gpu_or_raise()
    repo_url = str(git["repo"]).strip()
    clone_dir = repo_clone_dir(preset.name, requested_ref)

    _sync_repo(repo_url, requested_ref, clone_dir, quiet=quiet)
    bundle_root = find_bundle_root_in_clone(clone_dir, preset, gpu)
    commit = _git_head(clone_dir)

    bundle_ref_label = read_bundle_git_ref(bundle_root)
    if bundle_ref_label and bundle_ref_label != requested_ref:
        if not quiet:
            print(
                f"Note: flashcli-bundle.json git_ref={bundle_ref_label!r} "
                f"differs from checkout ref {requested_ref!r}"
            )

    _write_marker(
        preset.name,
        bundle_root=bundle_root,
        variant=variant_dir_name(gpu),
        git_ref=requested_ref,
        repo=repo_url,
        commit=commit,
    )

    if not quiet:
        print(
            f"Bundle ready: {bundle_root} "
            f"(ref {requested_ref!r}, {variant_dir_name(gpu)}, commit {commit[:8]})"
        )

    load_bundle_manifest(bundle_root)
    return bundle_root


def resolve_cached_bundle_root(
    preset: Preset,
    *,
    git_ref: str | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
) -> Path | None:
    """Return cached bundle root if active marker matches requested git ref."""
    override = git_ref or bundle_ref or bundle_version
    requested = resolve_requested_git_ref(preset, override)
    marker = read_bundle_marker(preset.name)
    if marker is None:
        return None
    if _marker_git_ref(marker) != requested:
        return None
    root = Path(str(marker.get("bundle_root", ""))).expanduser()
    if is_bundle_root(root):
        return root.resolve()
    return None


def list_bundle_refs_for_preset(preset: Preset) -> list[str]:
    return list(list_catalog_refs(preset).keys())


def list_cached_refs(preset_name: str) -> list[str]:
    """Refs that already have a local clone under ``refs/``."""
    root = bundle_preset_cache(preset_name) / "refs"
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / ".git").is_dir()
    )


# Backward-compatible aliases
list_bundle_versions_for_preset = list_bundle_refs_for_preset
find_variant_dir = find_bundle_root_in_clone


def find_variant_env_dir(
    repo_root: Path,
    preset: Preset,
    gpu: GpuInfo,
) -> Path:
    """Parent of bundle root: ``variants/<env>/`` (flat layout)."""
    root = find_bundle_root_in_clone(repo_root, preset, gpu)
    return root.parent
