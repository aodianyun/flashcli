"""Keep Hugging Face CLI downloads readable: tqdm only, no extra log noise."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator

_HUB_QUIET_LOGGERS = (
    "huggingface_hub",
    "httpx",
    "httpcore",
    "urllib3",
    "filelock",
    "fsspec",
    "huggingface_hub.file_download",
    "huggingface_hub.hf_api",
)


def apply_hub_quiet_env(env: dict[str, str]) -> dict[str, str]:
    """Env for ``hf download`` child: progress bars on, Hub logs off."""
    out = dict(env)
    out.setdefault("HF_HUB_VERBOSITY", "error")
    out.setdefault("TRANSFORMERS_VERBOSITY", "error")
    out.setdefault("PYTHONWARNINGS", "ignore")
    out.pop("HF_HUB_DISABLE_PROGRESS_BARS", None)
    return out


def hf_download_verbose() -> bool:
    return os.environ.get("FLASHCLI_HF_VERBOSE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@contextlib.contextmanager
def suppress_hub_side_logs() -> Iterator[None]:
    """Mute Python loggers in the current process during an HF download."""
    if hf_download_verbose():
        yield
        return
    prev_disable = logging.root.manager.disable
    prev_levels: list[tuple[logging.Logger, int]] = []
    for name in _HUB_QUIET_LOGGERS:
        log = logging.getLogger(name)
        prev_levels.append((log, log.level))
        log.setLevel(logging.ERROR)
    try:
        logging.disable(logging.WARNING)
        yield
    finally:
        logging.disable(prev_disable)
        for log, level in prev_levels:
            log.setLevel(level)
