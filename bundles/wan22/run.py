"""Wan2.2 TI2V-5B RunEngine (engine mode).

Wraps FlashRT's official-pipeline frontend (``config="wan22_ti2v_5b"``).
flashcli parses ``run_options`` and passes ``phase=load`` options to ``load()``
and ``phase=predict`` options to ``predict()``; defaults come from the manifest.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults
from flashcli_bundle.preset import Preset


def _apply_wan_sdpa_fallback() -> None:
    """Rebind Wan's ``flash_attention`` to its SDPA-capable fallback.

    The official Wan pipeline's ``WanModel.forward`` calls ``flash_attention``
    (imported from ``wan.modules.attention``), which asserts the ``flash_attn``
    wheel — a wheel without a build for every (torch, CUDA, SM) combination.
    Wan ships its own SDPA fallback (``attention``) used when the wheel is
    absent; we rebind the model-module global so both self- and cross-attention
    route through it. That fallback auto-selects ``flash_attn`` when the wheel
    IS present (e.g. RTX 5090) and ``torch scaled_dot_product_attention``
    otherwise.

    This touches only vendored third-party (Wan) package state at runtime; it
    does not modify FlashRT source or the Wan source tree.
    """
    import importlib

    att = importlib.import_module("wan.modules.attention")
    model_mod = importlib.import_module("wan.modules.model")
    if getattr(model_mod, "flash_attention", None) is not att.attention:
        model_mod.flash_attention = att.attention


class RunEngine:
    """Wan2.2 TI2V-5B text/image-to-video engine."""

    def __init__(self) -> None:
        self._model: Any = None
        self._defaults: dict[str, Any] = {}

    def load(self, checkpoint: Path, preset: Preset, **options: Any) -> None:
        _apply_wan_sdpa_fallback()
        import flash_rt

        t0 = time.perf_counter()
        hardware = str(options.get("hardware") or "auto")
        self._model = flash_rt.load_model(
            str(Path(checkpoint).expanduser().resolve()),
            framework="torch",
            config="wan22_ti2v_5b",
            hardware=hardware,
        )
        print(f"[wan22] phase load_model={time.perf_counter() - t0:.1f}s "
              f"(offline HF_HUB_OFFLINE={__import__('os').environ.get('HF_HUB_OFFLINE', '0')})")
        bundle = active_bundle()
        if bundle is not None:
            self._defaults = run_option_defaults(bundle)

    def predict(
        self,
        *,
        prompt: str = "",
        images: list[Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del images
        if self._model is None:
            raise RuntimeError("RunEngine.load() not called before predict()")

        d = self._defaults
        merged = {"prompt": prompt, **kwargs}
        mode = str(option_value("mode", merged, d) or "t2v")
        width = int(option_value("width", merged, d))
        height = int(option_value("height", merged, d))
        frames = int(option_value("frames", merged, d))
        steps = int(option_value("steps", merged, d))
        shift = float(option_value("shift", merged, d))
        guide_scale = float(option_value("guide_scale", merged, d))
        seed = int(option_value("seed", merged, d))
        sample_solver = str(option_value("sample_solver", merged, d))
        offload_model = bool(option_value("offload_model", merged, d))
        teacache = bool(option_value("teacache", merged, d))
        teacache_threshold = float(option_value("teacache_threshold", merged, d))
        out = str(option_value("out", merged, d) or "wan22_out.mp4")
        negative_prompt = option_value("negative_prompt", merged, d)

        image = None
        if mode == "i2v":
            from PIL import Image

            img_arg = option_value("image", merged, d)
            if not img_arg:
                raise ValueError("mode='i2v' requires --image PATH")
            image = Image.open(str(Path(str(img_arg)).expanduser())).convert("RGB")

        t_sp = time.perf_counter()
        self._model.set_prompt(str(prompt), negative_prompt=(negative_prompt or None))
        print(f"[wan22] phase set_prompt(T5 load+encode)={time.perf_counter() - t_sp:.1f}s")
        t0 = time.perf_counter()
        result = self._model.infer(
            mode=mode,
            image=image,
            width=width,
            height=height,
            frames=frames,
            steps=steps,
            shift=shift,
            guide_scale=guide_scale,
            seed=seed,
            sample_solver=sample_solver,
            offload_model=offload_model,
            teacache=teacache,
            teacache_threshold=teacache_threshold,
            save_path=str(Path(out).expanduser().resolve()),
            return_metadata=True,
        )
        meta = dict(result.get("metadata", {}))
        meta.setdefault("infer_seconds", time.perf_counter() - t0)
        meta["out"] = str(Path(out).expanduser().resolve())
        peak = meta.get("peak_allocated_gib")
        print(
            f"[wan22] infer={meta.get('infer_seconds', 0):.2f}s "
            f"peak={'%.2f' % peak if peak is not None else 'n/a'} GiB -> {meta['out']}"
        )
        return meta
