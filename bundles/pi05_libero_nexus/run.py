"""Pi0.5 LIBERO RunEngine — engine mode, single-shot inference via FlashRT.

This engine performs a one-shot ``predict()`` against the Pi0.5 policy,
matching the legacy ``pi05_libero`` bundle's behaviour. For stateful
episode control (snapshot / reset / fork), use ``flashcli serve`` on the
same bundle — ``serve.py`` is Nexus-backed and exposes the capsule verbs.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

from _pi05_compat import prepare_flash_rt_kernels
from _pi05_infer import (
    load_images_from_paths,
    placeholder_images,
    predict_pi05,
)

from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults


class RunEngine:
    """Pi0.5 LIBERO single-shot RunEngine."""

    def __init__(self) -> None:
        self._model: Any = None
        self._defaults: dict[str, Any] = {}

    def load(self, checkpoint: Path, preset: Any, **options: Any) -> None:
        bundle = active_bundle()
        if bundle is not None:
            self._defaults = run_option_defaults(bundle)

        prepare_flash_rt_kernels(quiet=True)
        import flash_rt

        num_views   = int(option_value("num_views", options, self._defaults) or 2)
        autotune    = int(option_value("autotune", options, self._defaults) or 3)
        config      = str(option_value("config", options, self._defaults) or "pi05")
        hardware    = str(option_value("hardware", options, self._defaults) or "auto")
        use_fp8     = bool(option_value("use_fp8", options, self._defaults))
        framework   = str(option_value("framework", options, self._defaults) or "torch")

        t0 = time.perf_counter()
        self._model = flash_rt.load_model(
            checkpoint=str(Path(checkpoint).expanduser().resolve()),
            framework=framework,
            num_views=num_views,
            autotune=autotune,
            config=config,
            hardware=hardware,
            use_fp8=use_fp8,
        )
        dt = time.perf_counter() - t0
        prec = "FP8" if use_fp8 else "BF16"
        print(f"[pi05_libero_nexus] load {prec} {dt:.1f}s "
              f"({hardware}, {num_views} views)")

    def predict(self, **kwargs: Any) -> dict[str, Any]:
        if self._model is None:
            raise RuntimeError("RunEngine.load() not called before predict()")

        prompt     = str(option_value("prompt", kwargs, self._defaults))
        image_raw  = option_value("image", kwargs, self._defaults)
        num_views  = int(option_value("num_views", kwargs, self._defaults) or 2)
        benchmark  = int(option_value("benchmark", kwargs, self._defaults) or 0)
        warmup     = int(option_value("warmup", kwargs, self._defaults) or 0)
        quiet      = bool(option_value("quiet", kwargs, self._defaults))

        image_paths: list[Path] | None = None
        if image_raw:
            parts = [p.strip() for p in str(image_raw).split(",") if p.strip()]
            image_paths = [Path(p) for p in parts] if parts else None

        def _one() -> Any:
            images: list[Any] | None = None
            if image_paths:
                images = load_images_from_paths(
                    image_paths, num_views=num_views)
            return predict_pi05(
                self._model,
                prompt=prompt,
                num_views=num_views,
                images=images,
            )

        for _ in range(max(0, warmup)):
            _one()

        if benchmark > 0:
            times: list[float] = []
            last: Any = None
            for _ in range(benchmark):
                t0 = time.perf_counter()
                last = _one()
                times.append(time.perf_counter() - t0)
            if not quiet and times:
                mean_s = statistics.mean(times)
                p50 = sorted(times)[len(times) // 2]
                print(f"benchmark n={len(times)} mean={mean_s:.3f}s p50={p50:.3f}s")
            actions = last
        else:
            t0 = time.perf_counter()
            actions = _one()
            dt = time.perf_counter() - t0
            if not quiet:
                print(f"[pi05_libero_nexus] predict {dt:.3f}s "
                      f"actions shape={getattr(actions, 'shape', '?')}")

        return {
            "actions_shape": list(getattr(actions, "shape", ())),
            "benchmark": benchmark,
            "warmup": warmup,
        }
