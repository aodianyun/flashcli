"""Download model weights from HuggingFace into the flashcli cache."""

from __future__ import annotations

import json
import os
import sys
import time
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
from flashcli.util.hub_quiet import hf_download_verbose, suppress_hub_side_logs


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


def _prepare_download_dest(
    dest: Path,
    *,
    quiet: bool,
    allow_patterns: list[str] | None = None,
    require_norm_stats: bool = False,
) -> None:
    """Ensure dest exists; keep partial Hub downloads so ``hf download`` can resume."""
    from flashcli.bundle.checkpoint import has_cached_weight_files

    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)
        return
    if has_cached_weight_files(
        dest, allow_patterns, require_norm_stats=require_norm_stats
    ):
        return
    try:
        entry_count = sum(1 for _ in dest.iterdir())
    except OSError:
        entry_count = 0
    if entry_count:
        if not quiet:
            print(
                f"Resuming incomplete HuggingFace download "
                f"({entry_count} cached entries): {dest}",
                file=sys.stderr,
            )
        return
    dest.mkdir(parents=True, exist_ok=True)


def _hf_download_retries() -> int:
    raw = os.environ.get("FLASHCLI_HF_DOWNLOAD_RETRIES", "3").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 3


def _hf_retry_sleep(attempt: int) -> float:
    raw = os.environ.get("FLASHCLI_HF_RETRY_DELAY", "5").strip()
    try:
        base = max(0.0, float(raw))
    except ValueError:
        base = 5.0
    return min(60.0, base * (attempt + 1))


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

    from flashcli.bundle.checkpoint import (
        has_cached_weight_files,
        weights_require_norm_stats,
    )

    patterns = _allow_patterns(spec)
    require_ns = weights_require_norm_stats(spec)
    if has_cached_weight_files(dest, patterns, require_norm_stats=require_ns):
        if not quiet:
            print(f"Weights already cached: {dest}", file=sys.stderr)
        return

    _prepare_download_dest(
        dest,
        quiet=quiet,
        allow_patterns=patterns,
        require_norm_stats=require_ns,
    )
    revision = spec.get("revision")
    rev = str(revision) if revision else None
    endpoint, explicit = _hf_endpoint_configured(spec)

    endpoints = download_endpoint_order(endpoint, explicit=explicit)
    if not explicit:
        endpoints = filter_download_endpoints(
            endpoints, repo=repo, revision=rev, quiet=quiet
        )

    errors: list[tuple[str, Exception]] = []
    max_retries = _hf_download_retries()
    with suppress_hub_side_logs():
        for idx, ep in enumerate(endpoints):
            label = endpoint_label(ep)
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    run_hf_cli_download(
                        repo,
                        dest,
                        revision=rev,
                        endpoint=ep,
                        allow_patterns=patterns,
                        quiet=quiet,
                    )
                    if has_cached_weight_files(
                        dest, patterns, require_norm_stats=require_ns
                    ):
                        return
                    last_exc = RuntimeError(
                        "Hub CLI exited successfully but checkpoint files are missing"
                    )
                except Exception as exc:
                    last_exc = exc
                if attempt + 1 >= max_retries:
                    break
                if not quiet:
                    print(
                        f"HuggingFace download failed ({label}), "
                        f"retry {attempt + 2}/{max_retries} in "
                        f"{_hf_retry_sleep(attempt):.0f}s ...",
                        file=sys.stderr,
                    )
                time.sleep(_hf_retry_sleep(attempt))
            if last_exc is not None:
                errors.append((label, last_exc))
            if idx + 1 < len(endpoints) and not quiet and hf_download_verbose():
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
        "  - Partial download: re-run `flashcli pull` to resume (cache is kept)\n"
        "  - Corrupt cache: rm -rf the destination dir and retry\n"
        "  - Unstable network: export FLASHCLI_HF_MAX_WORKERS=1\n"
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
            _download_huggingface(spec, extra_dir, quiet=quiet)

    _write_marker(cache_dir, preset.name, checkpoint_dir)
    _run_post_pull(preset, checkpoint_dir, quiet=quiet)
    apply_preset_env(preset)
    return checkpoint_dir
