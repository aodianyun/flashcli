"""Message conversion for Qwen3-VL bundle (OpenAI <-> frontend format)."""

from __future__ import annotations

import base64
import io
import urllib.request
from pathlib import Path
from typing import Any

from flashcli_bundle.protocol import ChatMessage, ChatRequest


def resolve_processor_tokenizer(processor: Any) -> Any:
    """Return the HF tokenizer from a Processor or pass through a bare tokenizer."""
    tok = getattr(processor, "tokenizer", None)
    return processor if tok is None else tok


DEFAULT_VL_PROCESSOR_REPOS: tuple[str, ...] = (
    "Qwen/Qwen3-VL-8B-Instruct",
)

_MIN_TRANSFORMERS_VERSION = (4, 57, 0)


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.split(".")[:3]:
        num = piece.split("+", 1)[0].split("-", 1)[0]
        for prefix in ("a", "b", "rc"):
            if prefix in num:
                num = num.split(prefix, 1)[0]
        parts.append(int(num or "0"))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def qwen3_vl_transformers_version_error() -> str | None:
    """Return an actionable error when ``transformers`` is too old for Qwen3-VL."""
    import importlib

    mod = importlib.import_module("transformers")
    current = _parse_version(str(getattr(mod, "__version__", "0.0.0")))
    if current >= _MIN_TRANSFORMERS_VERSION:
        return None
    if getattr(mod, "Qwen3VLProcessor", None) is None:
        return (
            f"transformers {mod.__version__} does not include Qwen3VLProcessor; "
            f"upgrade to >=4.57.0 (bundle manifest pins transformers>=4.57.0). "
            "With an older runtime, AutoProcessor loads a bare tokenizer even when "
            "preprocessor_config.json exists."
        )
    return None


def require_qwen3_vl_transformers() -> None:
    err = qwen3_vl_transformers_version_error()
    if err is not None:
        raise RuntimeError(err)

_VL_PROCESSOR_PATTERNS: tuple[str, ...] = (
    "preprocessor_config.json",
    "video_preprocessor_config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.json",
    "merges.txt",
    "chat_template.json",
    "special_tokens_map.json",
    "processor_config.json",
)


def _processor_cache_dir(repo: str) -> str:
    import os
    from pathlib import Path

    safe = repo.replace("/", "--")
    root = os.environ.get("FLASHCLI_PROCESSOR_CACHE")
    if root:
        return str(Path(root).expanduser() / safe)
    return str(Path.home() / ".flashcli" / "processor_cache" / safe)


def _cache_vl_processor_sidecars(repo: str) -> str | None:
    """Download processor JSON sidecars once; reuse from local cache."""
    import logging
    import os

    log = logging.getLogger(__name__)
    cache_dir = _processor_cache_dir(repo)
    preproc = os.path.join(cache_dir, "preprocessor_config.json")
    if os.path.isfile(preproc):
        return cache_dir

    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=repo,
            local_dir=cache_dir,
            allow_patterns=list(_VL_PROCESSOR_PATTERNS),
        )
    except Exception as exc:
        log.warning("failed to cache VL processor sidecars from %s: %s", repo, exc)
        return None

    return cache_dir if os.path.isfile(preproc) else None


def has_image_processor(processor: Any) -> bool:
    return getattr(processor, "image_processor", None) is not None


def configure_vl_max_pixels(processor: Any, max_pixels: int | None) -> None:
    """Cap vision token count via the processor's smart_resize budget (total pixels)."""
    if max_pixels is None:
        return
    cap = int(max_pixels)
    for proc in (
        getattr(processor, "image_processor", None),
        getattr(processor, "video_processor", None),
    ):
        if proc is None:
            continue
        if hasattr(proc, "max_pixels"):
            proc.max_pixels = cap
        size = getattr(proc, "size", None)
        if isinstance(size, dict):
            size["longest_edge"] = cap
        elif size is not None:
            try:
                size["longest_edge"] = cap
            except Exception:
                pass


def vl_processor_call_kwargs(max_pixels: int | None) -> dict[str, Any]:
    """Keyword args for ``Qwen3VLProcessor.__call__`` (transformers 4.57+)."""
    if max_pixels is None:
        return {}
    return {"max_pixels": int(max_pixels)}


def _try_load_vl_processor(path_or_repo: str) -> Any | None:
    import importlib
    import logging

    from transformers import AutoProcessor

    log = logging.getLogger(__name__)
    last_err: Exception | None = None

    try:
        obj = AutoProcessor.from_pretrained(path_or_repo, trust_remote_code=True)
        if has_image_processor(obj):
            return obj
    except Exception as exc:
        last_err = exc

    mod = importlib.import_module("transformers")
    for class_name in (
        "Qwen3VLProcessor",
        "Qwen2_5_VLProcessor",
        "Qwen2VLProcessor",
    ):
        cls = getattr(mod, class_name, None)
        if cls is None:
            continue
        try:
            obj = cls.from_pretrained(path_or_repo, trust_remote_code=True)
            if has_image_processor(obj):
                return obj
        except Exception as exc:
            last_err = exc
            continue
    if last_err is not None:
        log.debug("VL processor load failed for %s: %s", path_or_repo, last_err)
    return None


def load_qwen3_vl_processor(
    checkpoint_path: str,
    *,
    fallback_repos: tuple[str, ...] = DEFAULT_VL_PROCESSOR_REPOS,
) -> Any:
    """Load a Qwen3-VL processor with ``image_processor``.

    NVFP4 checkpoints copied to ModelScope often omit ``preprocessor_config.json``
    and ``AutoProcessor`` then returns a bare tokenizer. Fall back to the
    official instruct repo for processor sidecars while keeping local weights.
    """
    import logging
    import os

    from transformers import AutoProcessor

    log = logging.getLogger(__name__)

    require_qwen3_vl_transformers()

    if not fallback_repos:
        fallback_repos = DEFAULT_VL_PROCESSOR_REPOS

    proc = _try_load_vl_processor(checkpoint_path)
    if proc is not None:
        return proc

    preproc_cfg = os.path.join(checkpoint_path, "preprocessor_config.json")
    if not os.path.isfile(preproc_cfg):
        log.warning(
            "checkpoint %s missing preprocessor_config.json; "
            "trying official VL processor repos: %s",
            checkpoint_path,
            ", ".join(fallback_repos),
        )

    obj = AutoProcessor.from_pretrained(checkpoint_path, trust_remote_code=True)
    if has_image_processor(obj):
        return obj

    for repo in fallback_repos:
        proc = _try_load_vl_processor(repo)
        if proc is not None:
            log.info("using VL processor from %s (weights stay at %s)", repo, checkpoint_path)
            return proc
        cached = _cache_vl_processor_sidecars(repo)
        if cached is not None:
            proc = _try_load_vl_processor(cached)
            if proc is not None:
                log.info(
                    "using cached VL processor sidecars from %s (weights stay at %s)",
                    repo,
                    checkpoint_path,
                )
                return proc

    log.warning(
        "checkpoint %s has no image_processor; text-only run works but "
        "multimodal needs preprocessor sidecars or HF access to %s",
        checkpoint_path,
        ", ".join(fallback_repos),
    )
    return obj


def _load_image(url_or_path: str):
    from PIL import Image

    if url_or_path.startswith("data:"):
        raw = base64.b64decode(url_or_path.split(",", 1)[1])
    elif url_or_path.startswith(("http://", "https://")):
        with urllib.request.urlopen(url_or_path) as resp:
            raw = resp.read()
    else:
        with open(url_or_path, "rb") as fh:
            raw = fh.read()
    return Image.open(io.BytesIO(raw)).convert("RGB")


def resolve_image_input(spec: str):
    """Load an RGB PIL image from a local path, HTTP(S) URL, or data URL."""
    text = spec.strip()
    if not text:
        raise ValueError("image spec is empty")
    if text.startswith("data:") or text.startswith(("http://", "https://")):
        return _load_image(text)
    path = Path(text).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    return _load_image(str(path))


def extract_images_from_messages(messages: list[dict[str, Any]]) -> list[Any]:
    images: list[Any] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image" and part.get("image") is not None:
                images.append(part["image"])
    return images


def run_messages_from_prompt_image(prompt: str, image_path: str) -> list[dict[str, Any]]:
    image = resolve_image_input(image_path)
    return [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt or "Describe this image."},
            ],
        }
    ]


def run_messages_from_prompt(
    prompt: str,
    *,
    image_path: str | None = None,
) -> list[dict[str, Any]]:
    if image_path:
        return run_messages_from_prompt_image(prompt, image_path)
    return [{"role": "user", "content": prompt or ""}]


def messages_from_request(req: ChatRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in req.messages:
        msg: dict[str, Any] = {"role": m.role}
        if m.content is not None:
            msg["content"] = m.content
        if m.tool_calls:
            msg["tool_calls"] = m.tool_calls
        out.append(msg)
    return out


def _convert_content_part(part: dict[str, Any]) -> dict[str, Any]:
    ptype = part.get("type")
    if ptype == "text":
        return {"type": "text", "text": part.get("text", "")}
    if ptype == "image_url":
        url = (part.get("image_url") or {}).get("url", "")
        return {"type": "image", "image": _load_image(url)}
    if ptype == "image":
        return part
    raise ValueError(f"unsupported message content part type: {ptype!r}")


def openai_messages_to_frontend(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, str) or content is None:
            entry: dict[str, Any] = {"role": role, "content": content or ""}
            if m.get("tool_calls"):
                entry["tool_calls"] = m["tool_calls"]
            out.append(entry)
            continue
        if not isinstance(content, list):
            raise ValueError("message.content must be string or list")
        parts = [_convert_content_part(p) for p in content if isinstance(p, dict)]
        out.append({"role": role, "content": parts})
    return out
