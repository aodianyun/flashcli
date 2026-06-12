"""Pi0.5 VLA RunEngine — thin wrapper over bundle ``flash_rt.load_model``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults
from flashcli_bundle.preset import Preset

import _pi05_compat


def load_images_from_paths(
    paths: list[Path],
    *,
    num_views: int,
    size: tuple[int, int] = (224, 224),
) -> list[np.ndarray]:
    from PIL import Image

    if not paths:
        raise ValueError("No image paths provided")
    loaded: list[np.ndarray] = []
    for path in paths:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        img = Image.open(path).convert("RGB")
        if size:
            img = img.resize(size)
        loaded.append(np.asarray(img, dtype=np.uint8))
    if len(loaded) == 1 and num_views > 1:
        loaded = loaded * num_views
    elif len(loaded) < num_views:
        raise ValueError(
            f"Need {num_views} image(s), got {len(paths)} path(s): "
            + ", ".join(str(p) for p in paths)
        )
    return loaded[:num_views]


def placeholder_images(num_views: int) -> list[np.ndarray]:
    img = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
    return [img] * max(1, num_views)


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

        _pi05_compat.prepare_flash_rt_kernels(quiet=True)

        import flash_rt

        self._model = flash_rt.load_model(
            checkpoint=str(checkpoint.expanduser().resolve()),
            framework=str(
                options.get("framework") or bundle.raw.get("framework", "torch")
            ),
            num_views=int(self._opt(options, "num_views")),
            autotune=int(self._opt(options, "autotune")),
            config=str(self._opt(options, "config")),
            hardware=str(self._opt(options, "hardware")),
            use_fp8=bool(self._opt(options, "use_fp8")),
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
        num_views = int(self._opt(merged, "num_views"))
        prompt_text = str(self._opt(merged, "prompt") or "")
        if image_paths:
            images = load_images_from_paths(image_paths, num_views=num_views)
        if not images:
            images = placeholder_images(num_views)
        return self._model.predict(images=images, prompt=prompt_text)
