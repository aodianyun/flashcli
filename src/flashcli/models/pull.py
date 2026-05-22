"""Download model weights from HuggingFace into the flashcli cache."""

from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from flashcli import config
from flashcli.bundle.checkpoint import has_usable_checkpoint
from flashcli.models.registry import Preset

# Default China mirror when HF_ENDPOINT is unset and the official Hub fails.
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"

_HUB_NETWORK_ERRORS = frozenset(
    {
        "LocalEntryNotFoundError",
        "OfflineModeIsEnabled",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutError",
        "SSLError",
        "ProxyError",
        "HTTPError",
        "RepositoryNotFoundError",
    }
)


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


def _hf_token() -> str | None:
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def _hf_endpoint_configured(spec: dict[str, Any]) -> tuple[str, bool]:
    """Return (endpoint URL, True if set in spec or HF_ENDPOINT env)."""
    from_spec = str(spec.get("endpoint", "")).strip()
    if from_spec:
        return from_spec, True
    from_env = os.environ.get("HF_ENDPOINT", "").strip()
    if from_env:
        return from_env, True
    return "", False


def _prefer_hf_mirror_first() -> bool:
    return os.environ.get("FLASHCLI_PREFER_HF_MIRROR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _download_endpoint_order(endpoint: str, *, explicit: bool) -> list[str]:
    """Endpoints to try in order (empty string = huggingface.co default)."""
    if explicit:
        return [endpoint]
    if _prefer_hf_mirror_first():
        return [HF_MIRROR_ENDPOINT, ""]
    return ["", HF_MIRROR_ENDPOINT]


def _hub_tqdm_classes() -> tuple[type, type] | tuple[None, None]:
    """tqdm classes with disable=False for Docker/K8s (non-TTY) downloads."""
    try:
        from tqdm.auto import tqdm as tqdm_base
    except ImportError:
        return None, None

    class _FlashcliHubTqdm(tqdm_base):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["disable"] = False
            kwargs.setdefault("file", sys.stderr)
            super().__init__(*args, **kwargs)

    return _FlashcliHubTqdm, _FlashcliHubTqdm


def _configure_hub_progress(*, quiet: bool) -> None:
    if quiet:
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        return
    os.environ.pop("HF_HUB_DISABLE_PROGRESS_BARS", None)
    try:
        from huggingface_hub.utils import enable_progress_bars

        enable_progress_bars()
    except ImportError:
        pass


def _apply_hub_progress_kwargs(kwargs: dict[str, Any], *, quiet: bool) -> None:
    if quiet:
        return
    outer, inner = _hub_tqdm_classes()
    if outer is None:
        return
    kwargs["tqdm_class"] = outer
    try:
        from huggingface_hub import snapshot_download

        params = inspect.signature(snapshot_download).parameters
        if "inner_tqdm_class" in params and inner is not None:
            kwargs["inner_tqdm_class"] = inner
    except ImportError:
        pass


def _prepare_download_dest(dest: Path, *, quiet: bool) -> None:
    """Remove stale partial Hub caches so snapshot_download does not confuse them."""
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


def _snapshot_download(
    repo: str,
    dest: Path,
    *,
    revision: Any,
    endpoint: str,
    quiet: bool,
    spec: dict[str, Any],
) -> None:
    from huggingface_hub import snapshot_download

    _configure_hub_progress(quiet=quiet)

    kwargs: dict[str, Any] = {
        "repo_id": repo,
        "local_dir": str(dest),
        "local_dir_use_symlinks": False,
    }
    if revision:
        kwargs["revision"] = str(revision)
    if endpoint:
        kwargs["endpoint"] = endpoint
    token = _hf_token()
    if token:
        kwargs["token"] = token
    patterns = spec.get("allow_patterns")
    if isinstance(patterns, list) and patterns:
        kwargs["allow_patterns"] = [str(p) for p in patterns]
    _apply_hub_progress_kwargs(kwargs, quiet=quiet)
    if not quiet:
        rev_note = f" (revision={revision})" if revision else ""
        hub = endpoint or "huggingface.co"
        print(
            f"Downloading HuggingFace weights: {repo}{rev_note}\n"
            f"  Hub: {hub}\n"
            f"  -> {dest}",
            file=sys.stderr,
        )
    snapshot_download(**kwargs)


def _network_hint(errors: list[tuple[str, Exception]]) -> str:
    if not any(type(err).__name__ in _HUB_NETWORK_ERRORS for _, err in errors):
        return ""
    return (
        "\n  Network note:\n"
        "  - LocalEntryNotFoundError often means the Hub API was unreachable "
        "(DNS/firewall/proxy), not a missing repo.\n"
        "  - In K8s: set HTTPS_PROXY / HTTP_PROXY, or export "
        "HF_ENDPOINT=https://hf-mirror.com before flashcli pull/run.\n"
        "  - Prefer mirror first: export FLASHCLI_PREFER_HF_MIRROR=1\n"
        "  - Pre-download on a reachable host, then: "
        "flashcli run <preset> --checkpoint /path/to/checkpoint"
    )


def _download_huggingface(
    spec: dict[str, Any],
    dest: Path,
    *,
    quiet: bool,
) -> None:
    repo = str(spec.get("repo", "")).strip()
    if not repo:
        raise ValueError("HuggingFace weights spec requires non-empty 'repo'")

    if has_usable_checkpoint(dest):
        return

    _prepare_download_dest(dest, quiet=quiet)
    revision = spec.get("revision")
    endpoint, explicit = _hf_endpoint_configured(spec)

    errors: list[tuple[str, Exception]] = []
    endpoints = _download_endpoint_order(endpoint, explicit=explicit)

    for idx, ep in enumerate(endpoints):
        label = ep or "huggingface.co (default)"
        try:
            _snapshot_download(
                repo,
                dest,
                revision=revision,
                endpoint=ep,
                quiet=quiet,
                spec=spec,
            )
            if ep == HF_MIRROR_ENDPOINT and not quiet and not explicit:
                print(f"Download succeeded via {HF_MIRROR_ENDPOINT}")
            return
        except Exception as exc:
            errors.append((label, exc))
            if idx + 1 < len(endpoints) and not quiet:
                next_label = endpoints[idx + 1] or "huggingface.co (default)"
                print(
                    f"HuggingFace download failed ({label}); "
                    f"retrying via {next_label} ..."
                )

    rev_note = f" revision={revision!r}" if revision else ""
    attempts = "\n".join(
        f"  - {ep}: {type(err).__name__}: {err}" for ep, err in errors
    )
    mirror_note = ""
    if explicit:
        mirror_note = (
            f"\n  HF endpoint was set to {endpoint!r} (no automatic mirror retry)."
        )
    elif len(endpoints) > 1 and HF_MIRROR_ENDPOINT in endpoints:
        mirror_note = (
            f"\n  Tried Hub endpoints: {', '.join(ep or 'huggingface.co' for ep in endpoints)}."
        )
    raise RuntimeError(
        f"Failed to download HuggingFace repo {repo!r}{rev_note} -> {dest}\n"
        "  Attempts:\n"
        f"{attempts}\n"
        "  Checks:\n"
        "  - Network/VPN/proxy to huggingface.co "
        "(or export HF_ENDPOINT=https://hf-mirror.com)\n"
        "  - Gated repo: run `huggingface-cli login` or set HF_TOKEN\n"
        "  - Stale partial cache: rm -rf the destination dir and retry\n"
        "  - Local weights: flashcli run <preset> --checkpoint /path/to/ckpt"
        f"{mirror_note}"
        f"{_network_hint(errors)}"
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
