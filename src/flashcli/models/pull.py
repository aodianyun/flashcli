"""Download model weights from HuggingFace into the flashcli cache."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from flashcli import config
from flashcli.models.hf_hub import (
    HF_MIRROR_ENDPOINT,
    download_endpoint_order,
    endpoint_label,
    filter_download_endpoints,
    run_hf_cli_download,
)
from flashcli.models.registry import Preset


def _format_env_value(value: str) -> str:
    return value.format(models_dir=str(config.MODELS_DIR))


def apply_preset_env(preset: Preset) -> None:
    """Set process env vars declared in preset ``env`` (e.g. MTP ckpt dir)."""
    env_cfg = preset.raw.get("env") or {}
    if not isinstance(env_cfg, dict):
        return
    for key, value in env_cfg.items():
        if isinstance(value, str):
            os.environ[key] = _format_env_value(value)


def _hf_endpoint_configured(spec: dict[str, Any]) -> tuple[str, bool]:
    """Return (endpoint URL, True if set in spec or HF_ENDPOINT env)."""
    from_spec = str(spec.get("endpoint", "")).strip()
    if from_spec:
        return from_spec, True
    from_env = os.environ.get("HF_ENDPOINT", "").strip()
    if from_env:
        return from_env, True
    return "", False


def _prepare_download_dest(dest: Path, *, quiet: bool) -> None:
    """Remove stale partial caches before a fresh Hub CLI download."""
    from flashcli.bundle.checkpoint import has_usable_checkpoint

    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)
        return
    if has_usable_checkpoint(dest):
        return
    try:
        has_entries = any(dest.iterdir())
    except OSError:
        has_entries = False
    if has_entries:
        if not quiet:
            print(f"Removing incomplete checkpoint cache: {dest}")
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)


def _allow_patterns(spec: dict[str, Any]) -> list[str] | None:
    patterns = spec.get("allow_patterns")
    if isinstance(patterns, list) and patterns:
        return [str(p) for p in patterns]
    return None


def _download_huggingface(
    spec: dict[str, Any],
    dest: Path,
    *,
    quiet: bool,
) -> None:
    repo = str(spec.get("repo", "")).strip()
    if not repo:
        raise ValueError("HuggingFace weights spec requires non-empty 'repo'")

    from flashcli.bundle.checkpoint import has_usable_checkpoint

    if has_usable_checkpoint(dest):
        if not quiet:
            print(f"Weights already cached: {dest}", file=sys.stderr)
        return

    _prepare_download_dest(dest, quiet=quiet)
    revision = spec.get("revision")
    rev = str(revision) if revision else None
    endpoint, explicit = _hf_endpoint_configured(spec)
    patterns = _allow_patterns(spec)

    endpoints = download_endpoint_order(endpoint, explicit=explicit)
    if not explicit:
        endpoints = filter_download_endpoints(
            endpoints, repo=repo, revision=rev, quiet=quiet
        )

    errors: list[tuple[str, Exception]] = []
    for idx, ep in enumerate(endpoints):
        label = endpoint_label(ep)
        try:
            run_hf_cli_download(
                repo,
                dest,
                revision=rev,
                endpoint=ep,
                allow_patterns=patterns,
                quiet=quiet,
            )
            if ep == HF_MIRROR_ENDPOINT and not quiet:
                print(f"Download succeeded via {HF_MIRROR_ENDPOINT}", file=sys.stderr)
            return
        except Exception as exc:
            errors.append((label, exc))
            if idx + 1 < len(endpoints) and not quiet:
                next_label = endpoint_label(endpoints[idx + 1])
                print(
                    f"HuggingFace download failed ({label}); "
                    f"retrying via {next_label} ...",
                    file=sys.stderr,
                )

    rev_note = f" revision={revision!r}" if revision else ""
    attempts = "\n".join(
        f"  - {ep}: {type(err).__name__}: {err}" for ep, err in errors
    )
    hint = ""
    if not explicit:
        hint = (
            "\n  Tip: export HF_ENDPOINT=https://hf-mirror.com before flashcli "
            "(same as `hf download` / `huggingface-cli download`)."
        )
    raise RuntimeError(
        f"Failed to download HuggingFace repo {repo!r}{rev_note} -> {dest}\n"
        "  Attempts:\n"
        f"{attempts}\n"
        "  Checks:\n"
        "  - `hf download` or `huggingface-cli download` works with the same HF_ENDPOINT\n"
        "  - Gated repo: set HF_TOKEN or `hf auth login`\n"
        "  - Stale cache: rm -rf the destination dir and retry\n"
        "  - Local weights: flashcli run <preset> --checkpoint /path/to/ckpt"
        f"{hint}"
    )


def _run_post_pull(preset: Preset, checkpoint_dir: Path, *, quiet: bool) -> None:
    from flashcli.models.post_pull import run_post_pull_steps

    steps = preset.raw.get("post_pull") or []
    if not isinstance(steps, list):
        return
    run_post_pull_steps(steps, quiet=quiet)


def _write_marker(cache_dir: Path, preset_name: str, checkpoint_dir: Path) -> None:
    marker = {
        "preset": preset_name,
        "checkpoint": str(checkpoint_dir.resolve()),
    }
    (cache_dir / ".flashcli_model.json").write_text(
        json.dumps(marker, indent=2) + "\n",
        encoding="utf-8",
    )


def download_preset(preset: Preset, *, quiet: bool = False) -> Path:
    """Download main weights (+ extra_pull) for *preset* into the model cache."""
    cache_dir = config.MODELS_DIR / preset.name
    checkpoint_dir = cache_dir / "checkpoint"
    cache_dir.mkdir(parents=True, exist_ok=True)

    weights = preset.raw.get("weights") or {}
    source = str(weights.get("source", "huggingface")).lower()
    if source != "huggingface":
        raise NotImplementedError(f"Unsupported weights source: {source!r}")

    if not quiet:
        print(f"Downloading {preset.name} -> {checkpoint_dir}")
    _download_huggingface(weights, checkpoint_dir, quiet=quiet)

    extra_pull = preset.raw.get("extra_pull") or {}
    if isinstance(extra_pull, dict):
        for _key, spec in extra_pull.items():
            if not isinstance(spec, dict):
                continue
            repo = str(spec.get("repo", "")).strip()
            if not repo:
                if not quiet:
                    print(f"  extra_pull {_key!r}: repo not set, skipping")
                continue
            cache_name = str(spec.get("cache_name", _key))
            extra_dir = config.MODELS_DIR / cache_name
            if not quiet:
                print(f"  extra_pull {cache_name} -> {extra_dir}")
            _download_huggingface(spec, extra_dir, quiet=quiet)

    _write_marker(cache_dir, preset.name, checkpoint_dir)
    _run_post_pull(preset, checkpoint_dir, quiet=quiet)
    apply_preset_env(preset)
    return checkpoint_dir
