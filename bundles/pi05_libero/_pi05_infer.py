"""Pi0.5 inference helpers (bundle-local; no flashcli_bundle import)."""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np

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


def load_pi05_model(
    checkpoint: Path,
    *,
    num_views: int,
    autotune: int,
    config: str,
    hardware: str,
    use_fp8: bool,
    framework: str = "torch",
) -> Any:
    _pi05_compat.prepare_flash_rt_kernels(quiet=True)

    import flash_rt

    return flash_rt.load_model(
        checkpoint=str(checkpoint.expanduser().resolve()),
        framework=str(framework),
        num_views=int(num_views),
        autotune=int(autotune),
        config=str(config),
        hardware=str(hardware),
        use_fp8=bool(use_fp8),
    )


def predict_pi05(
    model: Any,
    *,
    prompt: str,
    num_views: int,
    image_paths: list[Path] | None = None,
    images: list[Any] | None = None,
) -> np.ndarray:
    prompt_text = str(prompt or "")
    if image_paths:
        images = load_images_from_paths(image_paths, num_views=num_views)
    if not images:
        images = placeholder_images(num_views)
    return model.predict(images=images, prompt=prompt_text)


def run_pi05_predict(
    model: Any,
    *,
    prompt: str,
    num_views: int,
    image_paths: list[Path] | None = None,
    images: list[Any] | None = None,
    warmup: int = 0,
    benchmark: int = 0,
    quiet: bool = False,
) -> np.ndarray:
    """Run predict once, or warmup + timed benchmark iterations."""

    def _one() -> np.ndarray:
        return predict_pi05(
            model,
            prompt=prompt,
            num_views=num_views,
            image_paths=image_paths,
            images=images,
        )

    for _ in range(max(0, warmup)):
        _one()

    if benchmark > 0:
        times: list[float] = []
        last: np.ndarray | None = None
        for _ in range(benchmark):
            t0 = time.perf_counter()
            last = _one()
            times.append(time.perf_counter() - t0)
        if not quiet and times:
            mean_s = statistics.mean(times)
            print(f"benchmark n={len(times)} mean={mean_s:.3f}s")
        assert last is not None
        return last

    return _one()
