"""FlashHub fetch error mapping for infer runtime."""

from __future__ import annotations

import re


class FlashHubError(RuntimeError):
    pass


class FlashHubNotFoundError(FlashHubError):
    pass


def _http_code_from_message(msg: str) -> int | None:
    match = re.search(r"\bHTTP Error (\d{3})\b", msg)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{3})\b", msg)
    if match and match.group(1).startswith(("4", "5")):
        return int(match.group(1))
    return None


def flashhub_error_from_fetch(url: str, exc: BaseException) -> FlashHubError:
    msg = str(exc)
    code = _http_code_from_message(msg)
    if code == 404:
        return FlashHubNotFoundError(f"FlashHub repo not found: {url}")
    if code is not None:
        return FlashHubError(f"FlashHub request failed ({code}) for {url}")
    return FlashHubError(f"FlashHub request failed for {url}: {exc}")
