"""Serve protocol capability identifiers and compatibility rules."""

from __future__ import annotations

from typing import Any

OPENAI_CHAT = "openai.chat"
OPENAI_RESPONSES = "openai.responses"
OPENAI_COMPLETIONS = "openai.completions"
OPENAI_EMBEDDINGS = "openai.embeddings"
OPENAI_MODERATIONS = "openai.moderations"
OPENAI_AUDIO_TRANSCRIPTIONS = "openai.audio.transcriptions"
OPENAI_AUDIO_TRANSLATIONS = "openai.audio.translations"
OPENAI_AUDIO_SPEECH = "openai.audio.speech"
OPENAI_IMAGES_GENERATIONS = "openai.images.generations"
OPENAI_IMAGES_EDITS = "openai.images.edits"
OPENAI_IMAGES_VARIATIONS = "openai.images.variations"
OPENAI_VIDEOS = "openai.videos"
OPENAI_REALTIME = "openai.realtime"
ANTHROPIC_MESSAGES = "anthropic.messages"
ANTHROPIC_COUNT_TOKENS = "anthropic.count_tokens"
ANTHROPIC_MODELS = "anthropic.models"

SERVE_CAPABILITIES = frozenset(
    {
        OPENAI_CHAT,
        OPENAI_RESPONSES,
        OPENAI_COMPLETIONS,
        OPENAI_EMBEDDINGS,
        OPENAI_MODERATIONS,
        OPENAI_AUDIO_TRANSCRIPTIONS,
        OPENAI_AUDIO_TRANSLATIONS,
        OPENAI_AUDIO_SPEECH,
        OPENAI_IMAGES_GENERATIONS,
        OPENAI_IMAGES_EDITS,
        OPENAI_IMAGES_VARIATIONS,
        OPENAI_VIDEOS,
        OPENAI_REALTIME,
        ANTHROPIC_MESSAGES,
        ANTHROPIC_COUNT_TOKENS,
        ANTHROPIC_MODELS,
    }
)

# Legacy manifests without serve.capabilities keep the pre-capability host API.
LEGACY_SERVE_CAPABILITIES = (OPENAI_CHAT,)


def parse_serve_capabilities(raw: Any) -> tuple[list[str] | None, str | None]:
    """Parse an explicit serve.capabilities value.

    Returns ``(None, None)`` when the field is absent, ``(list, None)`` for a
    valid array, and ``(None, error)`` for a malformed value.
    """
    if not isinstance(raw, list):
        return None, "serve.capabilities must be an array of strings"
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            return None, "serve.capabilities must contain non-empty strings"
        out.append(item.strip())
    return out, None


def validate_serve_capabilities(
    spec: Any,
    *,
    label: str = "entry.serve",
) -> list[str]:
    """Validate the capabilities of one serve entry."""
    if spec is None:
        return []
    invalid = getattr(spec, "capabilities_invalid", None)
    if invalid:
        return [f"{label}.capabilities: {invalid}"]
    caps = getattr(spec, "capabilities", None)
    if caps is None:
        return []
    kind = getattr(spec, "kind", "python")
    mode = getattr(spec, "mode", "engine")
    if kind != "python" or mode != "engine":
        return [f"{label}.capabilities is only valid for python engine serve"]
    errors: list[str] = []
    seen: set[str] = set()
    for cap in caps:
        if cap not in SERVE_CAPABILITIES:
            errors.append(f"{label}.capabilities: unknown capability {cap!r}")
        elif cap in seen:
            errors.append(f"{label}.capabilities: duplicate capability {cap!r}")
        seen.add(cap)
    return errors


def effective_serve_capabilities(spec: Any) -> list[str]:
    """Resolve host-owned routes for a serve entry.

    Python engine entries without the field keep the legacy ``openai.chat``
    behavior. Native and script entries never get host-owned protocol routes.
    """
    if spec is None:
        return []
    if getattr(spec, "kind", "python") != "python":
        return []
    if getattr(spec, "mode", "engine") != "engine":
        return []
    caps = getattr(spec, "capabilities", None)
    if caps is None:
        return list(LEGACY_SERVE_CAPABILITIES)
    return list(caps)


def parse_serve_concurrency(raw: Any) -> tuple[int | None, str | None]:
    """Parse an explicit serve.concurrency value.

    Returns ``(None, None)`` when the field is absent, ``(value, None)`` for a
    valid integer, and ``(None, error)`` for a malformed value.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None, "serve.concurrency must be an integer"
    if raw < 1:
        return None, "serve.concurrency must be >= 1"
    return raw, None


def validate_serve_concurrency(
    spec: Any,
    *,
    label: str = "entry.serve",
) -> list[str]:
    """Validate the concurrency of one serve entry."""
    if spec is None:
        return []
    invalid = getattr(spec, "concurrency_invalid", None)
    if invalid:
        return [f"{label}.concurrency: {invalid}"]
    if getattr(spec, "concurrency", None) is None:
        return []
    kind = getattr(spec, "kind", "python")
    mode = getattr(spec, "mode", "engine")
    if kind != "python" or mode != "engine":
        return [f"{label}.concurrency is only valid for python engine serve"]
    return []


def effective_serve_concurrency(spec: Any) -> int:
    """Resolve the inference concurrency for a serve entry (default 1)."""
    if spec is None:
        return 1
    value = getattr(spec, "concurrency", None)
    if value is None:
        return 1
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1
