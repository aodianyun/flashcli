"""Download model weights from HuggingFace into the flashcli cache."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flashcli import config
from flashcli.models.registry import Preset

# Default China mirror when HF_ENDPOINT is unset and the official Hub fails.
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"


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


def _snapshot_download(
    repo: str,
    dest: Path,
    *,
    revision: Any,
    endpoint: str,
    quiet: bool,
) -> None:
    from huggingface_hub import snapshot_download

    kwargs: dict[str, Any] = {
        "repo_id": repo,
        "local_dir": str(dest),
        "local_dir_use_symlinks": False,
    }
    if revision:
        kwargs["revision"] = str(revision)
    if endpoint:
        kwargs["endpoint"] = endpoint
    if quiet:
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    snapshot_download(**kwargs)


def _download_huggingface(
    spec: dict[str, Any],
    dest: Path,
    *,
    quiet: bool,
) -> None:
    repo = str(spec.get("repo", "")).strip()
    if not repo:
        raise ValueError("HuggingFace weights spec requires non-empty 'repo'")

    dest.mkdir(parents=True, exist_ok=True)
    revision = spec.get("revision")
    endpoint, explicit = _hf_endpoint_configured(spec)

    errors: list[tuple[str, Exception]] = []

    try:
        _snapshot_download(
            repo, dest, revision=revision, endpoint=endpoint, quiet=quiet
        )
        return
    except Exception as exc:
        errors.append((endpoint or "huggingface.co (default)", exc))

    if not explicit:
        if not quiet:
            print(
                f"HuggingFace download failed; retrying via mirror {HF_MIRROR_ENDPOINT} ..."
            )
        try:
            _snapshot_download(
                repo,
                dest,
                revision=revision,
                endpoint=HF_MIRROR_ENDPOINT,
                quiet=quiet,
            )
            if not quiet:
                print(f"Download succeeded via {HF_MIRROR_ENDPOINT}")
            return
        except Exception as exc:
            errors.append((HF_MIRROR_ENDPOINT, exc))

    rev_note = f" revision={revision!r}" if revision else ""
    attempts = "\n".join(
        f"  - {ep}: {type(err).__name__}: {err}" for ep, err in errors
    )
    mirror_note = (
        f"\n  HF endpoint was set to {endpoint!r} (no automatic mirror retry)."
        if explicit
        else f"\n  Automatic mirror retry used {HF_MIRROR_ENDPOINT!r} after default Hub failed."
    )
    raise RuntimeError(
        f"Failed to download HuggingFace repo {repo!r}{rev_note} -> {dest}\n"
        "  Attempts:\n"
        f"{attempts}\n"
        "  Checks:\n"
        "  - Network/VPN/proxy to huggingface.co (or export HF_ENDPOINT=https://hf-mirror.com)\n"
        "  - Gated repo: run `huggingface-cli login` or set HF_TOKEN\n"
        "  - Stale partial cache: rm -rf the destination dir and retry\n"
        "  - Local weights: flashcli run <preset> --checkpoint /path/to/ckpt"
        f"{mirror_note}"
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
