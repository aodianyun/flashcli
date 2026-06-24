"""Pi0.5 LIBERO engine entry — ``RunEngine`` (flashcli_bundle protocol)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults
from flashcli_bundle.preset import Preset

from _pi05_infer import load_pi05_model, run_pi05_predict


class RunEngine:
    def __init__(self) -> None:
        self._model: Any = None
        self._defaults: dict[str, Any] = {}

    def _opt(self, overrides: dict[str, Any], name: str) -> Any:
        return option_value(name, overrides, self._defaults)

    def load(self, checkpoint: Path, preset: Preset, **options: Any) -> None:
        del preset
        bundle = active_bundle()
        if bundle is None:
            raise RuntimeError(
                "No active bundle; activate bundle runtime before RunEngine.load()"
            )
        self._defaults = run_option_defaults(bundle)
        framework = str(options.get("framework") or bundle.raw.get("framework", "torch"))

        self._model = load_pi05_model(
            checkpoint,
            num_views=int(self._opt(options, "num_views")),
            autotune=int(self._opt(options, "autotune")),
            config=str(self._opt(options, "config")),
            hardware=str(self._opt(options, "hardware")),
            use_fp8=bool(self._opt(options, "use_fp8")),
            framework=framework,
        )

    def predict(
        self,
        *,
        prompt: str = "",
        images: list[Any] | None = None,
        image_paths: list[Path] | None = None,
        **kwargs: Any,
    ) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("RunEngine.load() not called")
        merged = {"prompt": prompt, **kwargs}
        return run_pi05_predict(
            self._model,
            prompt=str(self._opt(merged, "prompt") or ""),
            num_views=int(self._opt(merged, "num_views")),
            image_paths=image_paths,
            images=images,
            warmup=int(kwargs.get("warmup_iters", 0)),
            benchmark=int(kwargs.get("benchmark", 0)),
            quiet=not bool(kwargs.get("echo", True)),
        )
