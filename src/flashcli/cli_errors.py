"""User-facing CLI error formatting (no Rich traceback for expected failures)."""

from __future__ import annotations

import os
import re
from typing import NoReturn
from urllib.parse import unquote, urlparse

import typer

from flashcli_bundle.options import BundleOptionsError
from flashcli.bundle.catalog import BundleCatalogError
from flashcli.bundle.preflight import BundleEnvironmentError
from flashcli_bundle.errors import BundleNotReadyError

_HTTP_CODE_RE = re.compile(r"HTTP Error (\d+)", re.I)
_FLASHHUB_REF_RE = re.compile(
    r"(?:/repos/|^)(flashcli-bundle/[^/\s:?]+(?::[^@\s/?]+)?(?:@[\w.-]+)?)"
)


class FlashHubError(RuntimeError):
    """FlashHub API or repo fetch failure (user-facing)."""


class FlashHubNotFoundError(FlashHubError):
    """FlashHub repo or manifest not found (HTTP 404)."""


_USER_FACING_TYPES: tuple[type[Exception], ...] = (
    BundleOptionsError,
    ValueError,
    FileNotFoundError,
    BundleEnvironmentError,
    BundleCatalogError,
    BundleNotReadyError,
    FlashHubError,
)


def _flashhub_ref_from_text(text: str) -> str | None:
    match = _FLASHHUB_REF_RE.search(text)
    if match:
        return unquote(match.group(1))
    parsed = urlparse(text)
    if parsed.path and "flashcli-bundle/" in parsed.path:
        tail = parsed.path.split("/repos/", 1)[-1].strip("/")
        if tail.startswith("flashcli-bundle/"):
            return unquote(tail)
    return None


def _http_code_from_message(msg: str) -> int | None:
    match = _HTTP_CODE_RE.search(msg)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def is_user_facing_error(exc: BaseException) -> bool:
    if isinstance(exc, _USER_FACING_TYPES):
        return True
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        if _http_code_from_message(msg) is not None:
            return True
        if any(
            token in msg
            for token in (
                "FlashHub",
                "Failed to fetch",
                "Failed to download",
                "Invalid preset ref",
                "Invalid JSON from",
            )
        ):
            return True
    if isinstance(exc, ImportError):
        return True
    return False


def exit_code_for(exc: BaseException) -> int:
    code = getattr(exc, "exit_code", None)
    if isinstance(code, int):
        return code
    return 1


def hints_for(exc: BaseException) -> list[str]:
    msg = str(exc)
    ref = _flashhub_ref_from_text(msg)
    hints: list[str] = []

    if isinstance(exc, FlashHubNotFoundError) or _http_code_from_message(msg) == 404:
        if ref:
            hints.append(
                f"FlashHub has no repo at {ref!r} — check the version tag "
                "(e.g. flashcli-bundle/qwen_nvfp4:1.0.1@qwen3)."
            )
        else:
            hints.append(
                "Check the ref and version on FlashHub "
                "(e.g. flashcli-bundle/qwen_nvfp4:1.0.1@qwen3)."
            )
        hints.append("Run: flashcli models list")
        return hints

    if isinstance(exc, BundleEnvironmentError):
        hints.append("Run: flashcli models envs <ref>  — compare GPU/CUDA/Python cells.")
        return hints

    if isinstance(exc, BundleCatalogError):
        hints.append(
            "Use a FlashHub ref (flashcli-bundle/name:version[@variant]) "
            "or a local path (bundles/name[@variant])."
        )
        return hints

    if isinstance(exc, ValueError) and "Invalid preset ref" in msg:
        hints.append(
            "Examples: flashcli-bundle/pi05_libero:1.0.4, "
            "flashcli-bundle/qwen_nvfp4:1.0.1@qwen36, bundles/qwen_nvfp4@qwen3"
        )
        return hints

    if isinstance(exc, FileNotFoundError):
        hints.append("Use --checkpoint PATH to override weights, or run: flashcli pull <ref>")
        return hints

    if "Failed to fetch" in msg or "Failed to download" in msg:
        hints.append("Check network, FLASHCLI_FLASHHUB_API, and HF_ENDPOINT if pulling weights.")
        return hints

    return hints


def format_user_error(exc: BaseException) -> str:
    msg = str(exc).rstrip()
    # Multi-line expected failures keep their own layout; prefix only the first line.
    if "\n" in msg:
        first, rest = msg.split("\n", 1)
        lines = [f"error: {first}", rest]
    else:
        lines = [f"error: {msg}"]
    for hint in hints_for(exc):
        lines.append(f"hint: {hint}")
    return "\n".join(lines)


def handle_cli_error(exc: BaseException) -> NoReturn:
    if os.environ.get("FLASHCLI_DEBUG"):
        raise exc
    if not is_user_facing_error(exc):
        raise exc
    typer.echo(format_user_error(exc), err=True)
    raise typer.Exit(exit_code_for(exc)) from None


def flashhub_error_from_fetch(url: str, exc: BaseException) -> FlashHubError:
    """Map HTTP fetch failures to user-facing FlashHub errors."""
    msg = str(exc)
    code = _http_code_from_message(msg)
    ref = _flashhub_ref_from_text(url) or _flashhub_ref_from_text(msg)
    if code == 404:
        label = ref or url
        return FlashHubNotFoundError(f"FlashHub repo not found: {label}")
    if code is not None:
        label = ref or url
        return FlashHubError(f"FlashHub request failed ({code}) for {label}")
    return FlashHubError(f"FlashHub request failed for {url}: {exc}")
