"""Post-pull asset steps (tokenizer files, etc.) for model presets."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from flashcli.util.download_progress import download_url_to_path

PALIGEMMA_TOKENIZER_URL = (
    "https://storage.googleapis.com/big_vision/paligemma_tokenizer.model"
)
PALIGEMMA_TOKENIZER_MD5 = "1420adc9856720a559e8a87284b195e2"
PALIGEMMA_DEFAULT_CACHE = Path.home() / ".cache" / "flash_rt"


def default_paligemma_tokenizer_path() -> Path:
    """Same default as ``scripts/download_paligemma_tokenizer.sh``."""
    override = os.environ.get("FLASH_RT_PALIGEMMA_TOKENIZER", "").strip()
    if override:
        return Path(override).expanduser()
    return PALIGEMMA_DEFAULT_CACHE / "paligemma_tokenizer.model"


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def paligemma_tokenizer_ready(path: Path | None = None) -> bool:
    dest = (path or default_paligemma_tokenizer_path()).expanduser()
    if not dest.is_file():
        return False
    try:
        return _md5_file(dest) == PALIGEMMA_TOKENIZER_MD5
    except OSError:
        return False


def ensure_paligemma_tokenizer(
    *,
    dest: Path | None = None,
    quiet: bool = False,
    force: bool = False,
) -> Path:
    """Download PaliGemma SentencePiece model if missing or corrupt."""
    target = (dest or default_paligemma_tokenizer_path()).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    if not force and paligemma_tokenizer_ready(target):
        if not quiet:
            print(f"PaliGemma tokenizer already present: {target}")
        os.environ.setdefault("FLASH_RT_PALIGEMMA_TOKENIZER", str(target.resolve()))
        return target.resolve()

    if target.is_file():
        if not quiet:
            print(f"Re-downloading PaliGemma tokenizer (integrity check failed): {target}")
        target.unlink()

    tmp = target.with_suffix(target.suffix + ".part")
    try:
        download_url_to_path(
            PALIGEMMA_TOKENIZER_URL,
            tmp,
            quiet=quiet,
            label=(
                f"paligemma_tokenizer.model (~4.1 MiB) -> {target}\n"
                f"  {PALIGEMMA_TOKENIZER_URL}"
            ),
            timeout=120,
        )
        actual = _md5_file(tmp)
        if actual != PALIGEMMA_TOKENIZER_MD5:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                "PaliGemma tokenizer MD5 mismatch after download "
                f"(expected {PALIGEMMA_TOKENIZER_MD5}, got {actual})"
            )
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    if not quiet:
        size = target.stat().st_size
        print(f"PaliGemma tokenizer ready ({size} bytes): {target}")

    resolved = target.resolve()
    os.environ["FLASH_RT_PALIGEMMA_TOKENIZER"] = str(resolved)
    return resolved


def run_post_pull_steps(
    steps: list[Any],
    *,
    quiet: bool = False,
) -> None:
    """Execute merged ``post_pull`` steps from bundle manifest."""
    for step in steps:
        if not isinstance(step, dict):
            continue
        tokenizer = step.get("tokenizer")
        if tokenizer == "paligemma":
            ensure_paligemma_tokenizer(quiet=quiet)
            continue
        if not quiet:
            print(f"post_pull: unknown step {step!r}, skipping")
