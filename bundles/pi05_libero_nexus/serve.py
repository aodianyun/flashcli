"""Pi0.5 LIBERO stateful ServeEngine — Nexus-backed episode serving.

Loads the bundle-isolated FlashRT-Nexus substrate (3 C libs + vendored
nexus_python) and drives an in-process ``EmbeddedSession`` that wraps the
Pi0.5 producer. Exposes:

- ``/v1/chat/completions`` (standard flashcli serve) — one ``act()`` per call
- ``/v1/session/snapshot`` + ``/v1/session/reset/{capsule}`` (register_routes)
  for episode reset / warm-start via Nexus capsule verbs
- ``/v1/substrate`` (register_routes) — ABI fingerprint for debugging

The engine follows the flashcli ``ServeEngine`` protocol; no protocol
extension is needed. Episode control is opt-in via the ``register_routes``
hook that flashcli already supports.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from _substrate_loader import load_substrate, substrate_dir

from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, serve_option_defaults
from flashcli_bundle.protocol import ChatRequest, ChatResult, ChatChunk, ServeEngine


_DEFAULT_PROMPT = "pick up the red block and place it in the tray"


def _env_key(bundle: Any) -> str:
    runtime_map = bundle.manifest.raw.get("runtime", {})
    return next(iter(runtime_map))


def _dump_minimal_yaml(d: dict, path: Path) -> None:
    """Dump a dict in the tiny YAML subset Nexus manifest.py accepts.

    No lists, no flow style; nested mappings use 2-space indent; scalars
    are stringified with YAML-compatible quoting where needed.
    """
    lines: list[str] = []

    def _emit(prefix: str, val: Any) -> None:
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, dict):
                    lines.append(f"{prefix}{k}:")
                    _emit(prefix + "  ", v)
                else:
                    if isinstance(v, bool):
                        s = "true" if v else "false"
                    elif v is None:
                        s = ""
                    else:
                        s = str(v)
                    lines.append(f"{prefix}{k}: {s}")
        else:
            lines.append(f"{prefix}{val}")

    _emit("", d)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _to_uint8_rgb(im: Any) -> np.ndarray:
    if isinstance(im, np.ndarray):
        return np.ascontiguousarray(im.astype(np.uint8))
    if isinstance(im, (bytes, bytearray)):
        from PIL import Image
        import io
        return np.ascontiguousarray(
            np.array(Image.open(io.BytesIO(im)).convert("RGB")))
    if isinstance(im, str) and (im.startswith("http://") or im.startswith("https://")):
        import urllib.request
        from PIL import Image
        import io
        with urllib.request.urlopen(im, timeout=10) as r:
            return np.ascontiguousarray(
                np.array(Image.open(io.BytesIO(r.read())).convert("RGB")))
    if isinstance(im, str):
        from PIL import Image
        return np.ascontiguousarray(
            np.array(Image.open(im).convert("RGB")))
    raise TypeError(f"unsupported image type: {type(im)}")


class ServeEngine:
    """Stateful Pi0.5 serving backed by a Nexus EmbeddedSession."""

    def __init__(self) -> None:
        self._defaults: dict[str, Any] = {}
        self._session: Any = None          # nexus_python.embedded.EmbeddedSession
        self._sub: dict[str, Any] = {}
        self._num_views: int = 2
        self._model_id: str = "pi05-libero-nexus"

    # ------------------------------------------------------------------
    # ServeEngine protocol
    # ------------------------------------------------------------------
    @property
    def model_id(self) -> str:
        return self._model_id

    def load(self, checkpoint: Path, preset: Any, **options: Any) -> None:
        bundle = active_bundle()
        if bundle is not None:
            self._defaults = serve_option_defaults(bundle)

        # 1) Load substrate (raises on ABI mismatch / missing .so)
        self._sub = load_substrate()
        sub = substrate_dir()

        # 2) Resolve options
        num_views  = int(option_value("num_views", options, self._defaults) or 2)
        precision  = str(option_value("precision", options, self._defaults) or "fp8")
        stage_plan = str(option_value("stage_plan", options, self._defaults) or "full")
        hardware   = str(option_value("hardware", options, self._defaults) or "auto")
        warmup_prompt = str(option_value("warmup_prompt", options, self._defaults)
                            or _DEFAULT_PROMPT)
        capsule_dir  = str(option_value("capsule_dir", options, self._defaults) or "")
        self._num_views = num_views

        # 3) Build the in-memory Nexus manifest. Producer plugin loads
        #    flash_rt + the model + builds frt_model_runtime_v1; Nexus
        #    adopts it via flashrt_adopt_model_runtime.
        exec_so    = self._sub["exec_so"].name
        producer_so = self._sub["producer_so"].name
        nexus_so   = self._sub["nexus_so"].name

        manifest = {
            "model": {
                "checkpoint":  str(Path(checkpoint).expanduser().resolve()),
                "config":      "pi05",
                "framework":   "torch",
                "hardware":    hardware,
                "precision":   precision,
                "num_views":   num_views,
                "steps":       10,
                "stage_plan":  stage_plan,
                "io":          "native",
                "prompt":      warmup_prompt,
            },
            "producer": {
                "kind":         "python",
                "entry":        "nexus_python.producer_plugins.pi05:build",
                "flashrt_dir":  str(bundle.bundle_root.resolve()),
                "nexus_lib":    str(sub / nexus_so),
                "native_verbs": str(sub / producer_so),
            },
            "mode":  {"kind": "tick"},
            "serve": {"transport": "act_http", "host": "127.0.0.1", "port": "8080"},
            "state": {"capsule_dir": capsule_dir},
        }

        # 4) EmbeddedSession.open takes a path; dump to a per-deployment file
        manifest_path = bundle.bundle_root / ".build" / "nexus-manifest.yaml"
        _dump_minimal_yaml(manifest, manifest_path)

        # 5) Construct EmbeddedSession — runs SETUP→EXPORT→ADOPT→WARM
        from nexus_python.embedded import EmbeddedSession
        t0 = time.perf_counter()
        self._session = EmbeddedSession.open(str(manifest_path))
        dt = time.perf_counter() - t0
        v = self._sub["version"]
        print(f"[pi05_libero_nexus] substrate loaded "
              f"(flashrt={v['flashrt_short']}, nexus={v['nexus_short']}); "
              f"session open {dt:.1f}s ({precision}, {stage_plan})")

    def warmup(self, spec: str | None) -> None:
        # EmbeddedSession.open already ran one warmup tick internally.
        # Optional second warmup for graph caching.
        if self._session is None:
            return
        zeros = [np.zeros((224, 224, 3), dtype=np.uint8)
                 for _ in range(self._num_views)]
        prompt = str(self._defaults.get("warmup_prompt", _DEFAULT_PROMPT))
        try:
            self._session.act(zeros, prompt=prompt)
        except Exception as exc:  # noqa: BLE001
            print(f"[pi05_libero_nexus] warmup tick skipped: {exc}",
                  file=sys.stderr)

    def chat(self, request: ChatRequest) -> ChatResult:
        if self._session is None:
            raise RuntimeError("ServeEngine.load() not called")
        images = self._extract_images(request)
        # Note: the Pi0.5 native producer bakes the prompt at model-construction
        # time (see manifest `model.prompt` / serve_option `warmup_prompt`); it
        # does NOT expose a dynamic prompt/text port. Passing a different prompt
        # here would raise "this producer did not export a prompt/text port".
        # If you need a different task instruction, set it at load time via
        # `flashcli serve ... --warmup_prompt "..."` (or the manifest default).
        prompt = None  # use the baked-in producer prompt
        t0 = time.perf_counter()
        result = self._session.act(images, prompt=prompt)
        dt = (time.perf_counter() - t0) * 1000.0
        actions = getattr(result, "actions", None)
        chunk_id = getattr(result, "chunk_id", 0)
        shape = list(getattr(actions, "shape", ()))
        baked = self._defaults.get("warmup_prompt", "")
        return ChatResult(
            content=f"actions shape={shape}, latency={dt:.1f}ms, chunk={chunk_id}, "
                    f"prompt={baked!r} (baked at load)",
            usage={
                "latency_ms": dt,
                "chunk_id": chunk_id,
                "actions_shape": shape,
                "prompt": baked,
            },
        )

    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        # Pi0.5 is a single-step policy; map to a single chunk.
        r = self.chat(request)
        yield ChatChunk(content=r.content, finish_reason="stop")

    # ------------------------------------------------------------------
    # Episode control via flashcli's existing register_routes hook
    # (serve/app.py:112-113 calls engine.register_routes(app) if present)
    # ------------------------------------------------------------------
    def register_routes(self, app: Any) -> None:
        from fastapi import HTTPException
        from pydantic import BaseModel

        class SnapshotReq(BaseModel):
            name: str | None = None

        @app.post("/v1/session/snapshot")
        async def snapshot(req: SnapshotReq | None = None) -> dict:
            if self._session is None:
                raise HTTPException(503, "session not loaded")
            name = req.name if req else None
            cap = self._session.snapshot(name)
            return {"capsule": cap}

        @app.post("/v1/session/reset/{capsule}")
        async def reset(capsule: str) -> dict:
            if self._session is None:
                raise HTTPException(503, "session not loaded")
            try:
                self._session.reset(capsule)
            except KeyError:
                raise HTTPException(404, f"capsule {capsule!r} not found")
            return {"ok": True, "capsule": capsule}

        @app.get("/v1/substrate")
        async def substrate_info() -> dict:
            return self._sub["version"]

        @app.get("/v1/session/state")
        async def session_state() -> dict:
            if self._session is None:
                raise HTTPException(503, "session not loaded")
            return self._session.state()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _extract_images(self, request: ChatRequest) -> list[np.ndarray]:
        imgs = getattr(request, "images", None)
        if not imgs:
            extras = getattr(request, "extras", None) or {}
            imgs = extras.get("images") or extras.get("image")
        if imgs:
            if isinstance(imgs, (str, bytes, bytearray)):
                imgs = [imgs]
            return [_to_uint8_rgb(im) for im in imgs][: self._num_views]
        # fallback: zero images (caller did not supply vision input)
        return [np.zeros((224, 224, 3), dtype=np.uint8)
                for _ in range(self._num_views)]

    def _extract_prompt(self, request: ChatRequest) -> str:
        if request.messages:
            last = request.messages[-1]
            return getattr(last, "content", "") or ""
        return str(self._defaults.get("warmup_prompt", _DEFAULT_PROMPT))
