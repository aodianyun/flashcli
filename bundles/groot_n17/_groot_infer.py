"""GROOT N1.7 inference helpers (bundle-local; no flashcli_bundle import)."""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np

import _groot_compat
from _groot_n17_preprocess import preprocess_for_flashrt, release_policy


def load_groot_model(
    checkpoint: Path,
    *,
    num_views: int,
    embodiment_tag: str,
    action_horizon: int,
    autotune: int,
    config: str,
    hardware: str,
    use_fp8: bool,
    use_fp16: bool,
    framework: str = "torch",
) -> Any:
    _groot_compat.prepare_flash_rt_kernels(quiet=True)

    import flash_rt

    return flash_rt.load_model(
        checkpoint=str(checkpoint.expanduser().resolve()),
        framework=str(framework),
        num_views=int(num_views),
        embodiment_tag=str(embodiment_tag),
        action_horizon=int(action_horizon),
        autotune=int(autotune),
        config=str(config),
        hardware=str(hardware),
        use_fp8=bool(use_fp8) and not bool(use_fp16),
        use_fp16=bool(use_fp16),
    )


def preprocess_groot_n17(
    checkpoint: Path,
    *,
    prompt: str,
    embodiment_tag: str,
    num_views: int,
    image_paths: list[Path] | None = None,
    state_path: Path | str | None = None,
    seed: int = 0,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Run Gr00tPolicy obs→aux capture and release policy VRAM before FlashRT load."""
    aux, state_dict, _parsed, policy = preprocess_for_flashrt(
        checkpoint,
        embodiment_tag=embodiment_tag,
        prompt=prompt,
        num_views=num_views,
        image_paths=image_paths,
        state_path=state_path,
        seed=seed,
    )
    release_policy(policy)
    return aux, state_dict


def _pipe(model: Any) -> Any:
    pipe = getattr(model, "_pipe", model)
    if not hasattr(pipe, "set_prompt") or not hasattr(pipe, "infer"):
        raise RuntimeError("FlashRT model does not expose set_prompt/infer (expected groot_n17)")
    return pipe


def run_groot_infer_n17(
    model: Any,
    aux: dict[str, Any],
    state_dict: dict[str, np.ndarray],
    *,
    prompt: str,
    action_horizon: int = 40,
    warmup: int = 0,
    benchmark: int = 0,
    quiet: bool = False,
    denormalize: bool = True,
) -> np.ndarray | dict[str, np.ndarray]:
    """FlashRT set_prompt + infer using pre-captured aux."""

    pipe = _pipe(model)
    pipe.set_prompt(aux=aux, prompt=str(prompt or ""))

    state_normed = pipe.normalize_state(state_dict)
    noise = aux["initial_noise"]
    if hasattr(pipe, "device"):
        noise = noise.to(pipe.device)
    noise = noise.bfloat16()

    def _infer_once() -> np.ndarray | dict[str, np.ndarray]:
        out_normed = pipe.infer(
            state_normed,
            initial_noise=noise,
            action_horizon=int(action_horizon),
        )
        if not denormalize:
            return out_normed.detach().float().cpu().numpy()
        denorm = pipe.denormalize_action(out_normed, state_dict=state_dict)
        return {key: value.detach().float().cpu().numpy() for key, value in denorm.items()}

    for _ in range(max(0, warmup)):
        _infer_once()

    if benchmark > 0:
        times: list[float] = []
        last: np.ndarray | dict[str, np.ndarray] | None = None
        for _ in range(benchmark):
            t0 = time.perf_counter()
            last = _infer_once()
            times.append(time.perf_counter() - t0)
        if not quiet and times:
            mean_s = statistics.mean(times)
            print(f"benchmark n={len(times)} mean={mean_s:.3f}s")
        assert last is not None
        return last

    return _infer_once()
