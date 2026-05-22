"""Pi0.5 VLA RunEngine — thin wrapper over bundle ``flash_rt.load_model``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from flashcli.bundle.activate import active_bundle
from flashcli.bundle.config import bundle_defaults
from flashcli.models.registry import Preset

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

    def load(self, checkpoint: Path, preset: Preset, **options: Any) -> None:
        del preset
        bundle = active_bundle()
        if bundle is None:
            raise RuntimeError(
                "No active bundle; activate bundle runtime before RunEngine.load()"
            )
        self._defaults = bundle_defaults(bundle)

        _pi05_compat.prepare_flash_rt_kernels(quiet=True)

        import flash_rt

        self._model = flash_rt.load_model(
            checkpoint=str(checkpoint.expanduser().resolve()),
            framework=str(
                options.get("framework") or bundle.raw.get("framework", "torch")
            ),
            num_views=int(options.get("num_views") or self._defaults.get("num_views", 2)),
            autotune=int(options.get("autotune") or self._defaults.get("autotune", 3)),
            config=str(options.get("config") or bundle.raw.get("config", "pi05")),
            hardware=str(options.get("hardware") or self._defaults.get("hardware", "auto")),
            use_fp8=bool(
                options.get("use_fp8", self._defaults.get("use_fp8", True))
            ),
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
        if image_paths:
            num_views = int(kwargs.get("num_views") or self._defaults.get("num_views", 2))
            images = load_images_from_paths(image_paths, num_views=num_views)
        if not images:
            num_views = int(kwargs.get("num_views") or self._defaults.get("num_views", 2))
            images = placeholder_images(num_views)
        return self._model.predict(images=images, prompt=prompt)
