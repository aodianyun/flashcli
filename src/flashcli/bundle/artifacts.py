"""Download and assemble bundle artifacts (repo tree + per-env runtime/)."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from flashcli.bundle.flashhub import (
    RepoIndex,
    download_repo_file,
    fetch_repo_index,
)
from flashcli.bundle.layout import is_bundle_root
from flashcli.bundle.manifest import (
    BundleManifest,
    bundle_runtime_dir,
    bundle_runtime_map,
    load_bundle_manifest,
    load_bundle_manifest_data,
)
from flashcli.bundle.marker import (
    read_runtime_marker,
    write_preset_marker,
    write_runtime_marker,
)
from flashcli.bundle.preflight import PreflightResult, run_preflight
from flashcli.bundle.runtime_id import runtime_id_from_path, runtime_id_from_repo
from flashcli import config
from flashcli.models.registry import Preset


def _normalized_artifact_paths(runtime_map: dict[str, str]) -> list[str]:
    paths: list[str] = []
    for raw in runtime_map.values():
        p = str(raw).strip().lstrip("/").rstrip("/")
        if p:
            paths.append(p)
    return paths


def _should_download_repo_file(
    rel_path: str,
    *,
    runtime_map: dict[str, str],
    selected_artifact_rel: str,
) -> bool:
    norm = rel_path.strip().lstrip("/")
    selected = selected_artifact_rel.strip().lstrip("/").rstrip("/")
    for artifact_path in _normalized_artifact_paths(runtime_map):
        if artifact_path == selected:
            continue
        if norm == artifact_path or norm.startswith(artifact_path + "/"):
            return False
    return True


def _download_repo_tree(
    index: RepoIndex,
    bundle_root: Path,
    *,
    runtime_map: dict[str, str],
    selected_artifact_rel: str,
    quiet: bool,
    force: bool,
) -> None:
    bundle_root.mkdir(parents=True, exist_ok=True)
    pending = [
        entry
        for entry in index.files
        if (rel := entry.path.strip().lstrip("/"))
        and rel != "flashcli-bundle.json"
        and _should_download_repo_file(
            rel,
            runtime_map=runtime_map,
            selected_artifact_rel=selected_artifact_rel,
        )
    ]
    if not quiet and pending:
        print(
            f"Downloading bundle source tree ({len(pending)} file(s)) …",
            file=sys.stderr,
        )
    for entry in pending:
        rel = entry.path.strip().lstrip("/")
        dest = bundle_root / rel
        download_repo_file(entry, dest, quiet=quiet, force=force)


def _manifest_staging_path(repo_url: str) -> Path:
    key = hashlib.sha256(repo_url.strip().encode()).hexdigest()[:16]
    return config.CACHE_DIR / "repo-staging" / f"{key}-manifest.json"


def _runtime_is_ready(
    *,
    bundle_root: Path,
    manifest_cache: Path,
    marker: dict[str, Any],
    repo_url: str,
    env_key: str,
    artifact_rel: str,
    force: bool,
) -> bool:
    """True when cached bundle tree matches catalog repo + remote manifest + native artifacts."""
    if force:
        return False
    if marker.get("env_key") != env_key:
        return False
    if marker.get("repo_url") != repo_url:
        return False
    if not is_bundle_root(bundle_root):
        return False
    if not (bundle_root / "flash_rt").is_dir():
        return False
    if not _runtime_has_kernels(bundle_root, artifact_rel):
        return False
    local_manifest = bundle_root / "flashcli-bundle.json"
    if not local_manifest.is_file():
        return False
    try:
        if local_manifest.read_bytes() != manifest_cache.read_bytes():
            return False
    except OSError:
        return False
    return True


def runtime_layout(runtime_id: str) -> dict[str, Path]:
    from flashcli.bundle.marker import runtime_dir

    root = runtime_dir(runtime_id)
    return {
        "root": root,
        "bundle_root": root / "root",
        "venv": root / "venv",
        "cache": root / "cache",
    }


def _download_artifact(
    index: RepoIndex,
    rel_path: str,
    dest: Path,
    *,
    quiet: bool,
    force: bool,
) -> None:
    entry = index.find(rel_path)
    if entry is None:
        raise FileNotFoundError(
            f"Artifact {rel_path!r} not found in FlashHub repo {index.repo_url!r}"
        )
    download_repo_file(entry, dest, quiet=quiet, force=force)


def _runtime_has_kernels(bundle_root: Path, artifact_rel: str) -> bool:
    native_dir = bundle_root / artifact_rel.strip().lstrip("/")
    return native_dir.is_dir() and any(native_dir.glob("flash_rt_kernels*.so"))


def ensure_runtime_from_repo(
    preset: Preset,
    repo_url: str,
    *,
    quiet: bool = False,
    force: bool = False,
) -> tuple[str, Path, BundleManifest, PreflightResult]:
    """Manifest-first download; return (runtime_id, bundle_root, manifest, preflight)."""
    index = fetch_repo_index(repo_url, use_cache=not force)
    manifest_entry = index.find("flashcli-bundle.json")
    if manifest_entry is None:
        raise FileNotFoundError(f"No flashcli-bundle.json in {repo_url}")

    layout_cache = config.CACHE_DIR / "repo-staging"
    layout_cache.mkdir(parents=True, exist_ok=True)
    manifest_cache = _manifest_staging_path(repo_url)
    download_repo_file(manifest_entry, manifest_cache, quiet=quiet, force=force)
    manifest_data = json.loads(manifest_cache.read_text(encoding="utf-8"))
    manifest_sha256 = hashlib.sha256(manifest_cache.read_bytes()).hexdigest()

    runtime_id = runtime_id_from_repo(repo_url, str(manifest_data.get("name", preset.name)))
    layout = runtime_layout(runtime_id)
    layout["root"].mkdir(parents=True, exist_ok=True)
    layout["cache"].mkdir(parents=True, exist_ok=True)

    shutil.copy2(manifest_cache, layout["cache"] / "flashcli-bundle.json")
    manifest = load_bundle_manifest_data(manifest_data, bundle_root=layout["bundle_root"])

    preflight = run_preflight(manifest)
    runtime_map = bundle_runtime_map(manifest)
    artifact_rel = str(runtime_map.get(preflight.env_key, "")).strip()
    if not artifact_rel:
        raise FileNotFoundError(
            f"No runtime artifact for environment {preflight.env_key!r} in manifest"
        )

    marker = read_runtime_marker(runtime_id) or {}
    bundle_root = layout["bundle_root"]
    ready = _runtime_is_ready(
        bundle_root=bundle_root,
        manifest_cache=manifest_cache,
        marker=marker,
        repo_url=repo_url,
        env_key=preflight.env_key,
        artifact_rel=artifact_rel,
        force=force,
    )

    if not ready:
        if not quiet:
            print(
                f"Syncing bundle from FlashHub ({repo_url}) …",
                file=sys.stderr,
            )
        if bundle_root.is_dir():
            shutil.rmtree(bundle_root, ignore_errors=True)
        bundle_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_cache, bundle_root / "flashcli-bundle.json")

        _download_repo_tree(
            index,
            bundle_root,
            runtime_map=runtime_map,
            selected_artifact_rel=artifact_rel,
            quiet=quiet,
            force=force,
        )

        if not _runtime_has_kernels(bundle_root, artifact_rel):
            artifact_local = bundle_root / artifact_rel
            if not artifact_local.is_file() and not artifact_local.is_dir():
                artifact_cache = layout["cache"] / Path(artifact_rel).name
                _download_artifact(index, artifact_rel, artifact_cache, quiet=quiet, force=force)
                if artifact_cache.is_dir():
                    dest = bundle_root / artifact_rel
                    dest.mkdir(parents=True, exist_ok=True)
                    for so in artifact_cache.glob("*.so"):
                        shutil.copy2(so, dest / so.name)
                elif artifact_cache.is_file():
                    dest = bundle_root / artifact_rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(artifact_cache, dest)

        if not _runtime_has_kernels(bundle_root, artifact_rel):
            raise FileNotFoundError(
                f"Missing flash_rt_kernels*.so under {artifact_rel!r} after sync"
            )
        manifest = load_bundle_manifest(bundle_root)

    write_runtime_marker(
        runtime_id,
        {
            "runtime_id": runtime_id,
            "repo_url": repo_url,
            "manifest_sha256": manifest_sha256,
            "env_key": preflight.env_key,
            "host_env_key": preflight.host_env_key,
            "python_abi": preflight.python_abi,
            "bundle_root": str(bundle_root),
            "preset": preset.name,
        },
    )
    write_preset_marker(
        preset.name,
        {
            "source": "repo",
            "repo": repo_url,
            "runtime_id": runtime_id,
            "bundle_root": str(bundle_root),
            "env_key": preflight.env_key,
        },
    )

    if not quiet:
        print(
            f"Bundle runtime ready: {bundle_root} "
            f"(runtime {preflight.env_key}, id {runtime_id}, repo {repo_url})"
        )

    return runtime_id, bundle_root, manifest, preflight


def ensure_runtime_from_path(
    preset: Preset,
    bundle_path: Path,
    *,
    quiet: bool = False,
) -> tuple[str, Path, BundleManifest, PreflightResult]:
    """Local dev bundle.path — preflight only, no FlashHub download."""
    bundle_path = bundle_path.expanduser().resolve()
    if not is_bundle_root(bundle_path):
        raise FileNotFoundError(f"Not a bundle root: {bundle_path}")

    manifest = load_bundle_manifest(bundle_path)
    preflight = run_preflight(manifest)
    runtime_id = runtime_id_from_path(str(bundle_path), manifest.name)

    native_dir = bundle_runtime_dir(manifest, preflight.env_key)
    if not native_dir.is_dir() or not any(native_dir.glob("flash_rt_kernels*.so")):
        raise FileNotFoundError(
            f"Local bundle {bundle_path} missing flash_rt_kernels*.so under "
            f"{native_dir.relative_to(bundle_path)!s} for {preflight.env_key!r}. "
            f"Run pack/release or build into runtime/{preflight.env_key}/."
        )

    write_runtime_marker(
        runtime_id,
        {
            "runtime_id": runtime_id,
            "source": "path",
            "path": str(bundle_path),
            "env_key": preflight.env_key,
            "host_env_key": preflight.host_env_key,
            "python_abi": preflight.python_abi,
            "bundle_root": str(bundle_path),
            "preset": preset.name,
        },
    )
    write_preset_marker(
        preset.name,
        {
            "source": "path",
            "path": str(bundle_path),
            "runtime_id": runtime_id,
            "bundle_root": str(bundle_path),
            "env_key": preflight.env_key,
        },
    )
    return runtime_id, bundle_path, manifest, preflight
