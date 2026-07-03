"""GROOT N1.7 obs/aux preprocessing via vendored Gr00tPolicy (bundle-local)."""

from __future__ import annotations

import functools
import gc
import json
from pathlib import Path
from typing import Any

import numpy as np

from _groot_hub_env import prepare_gr00t_n17_hub_env, resolve_vlm_model_path

_REQUIRED_AUX_KEYS = (
    "llm_input_embeds",
    "visual_pos_masks",
    "rope_cos",
    "rope_sin",
    "pixel_features",
    "grid_thw",
    "initial_noise",
)

_IDENTITY_ROT6D = np.array([1, 0, 0, 0, 1, 0], dtype=np.float32)


def load_images_from_paths(
    paths: list[Path | str],
    *,
    num_views: int,
) -> list[np.ndarray]:
    from PIL import Image

    if not paths:
        raise ValueError("No image paths provided")
    loaded: list[np.ndarray] = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        img = Image.open(path).convert("RGB")
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
    img = np.zeros((256, 256, 3), dtype=np.uint8)
    return [img] * max(1, num_views)


_VLM_PATCHED = False


def _install_vlm_local_path_patches() -> None:
    global _VLM_PATCHED
    if _VLM_PATCHED:
        return
    from gr00t.model.gr00t_n1d7 import processing_gr00t_n1d7 as proc
    from gr00t.model.modules import qwen3_backbone as qwen3_bb

    orig_backbone_init = qwen3_bb.Qwen3Backbone.__init__
    orig_build_processor = proc.build_processor

    @functools.wraps(orig_backbone_init)
    def _backbone_init(self, model_name: str = "nvidia/Cosmos-Reason2-2B", **kwargs):
        return orig_backbone_init(
            self, model_name=resolve_vlm_model_path(model_name), **kwargs
        )

    @functools.wraps(orig_build_processor)
    def _build_processor(model_name: str, transformers_loading_kwargs: dict):
        return orig_build_processor(
            resolve_vlm_model_path(model_name), transformers_loading_kwargs
        )

    qwen3_bb.Qwen3Backbone.__init__ = _backbone_init  # type: ignore[method-assign]
    proc.build_processor = _build_processor
    _VLM_PATCHED = True


def load_gr00t_policy(
    checkpoint: Path,
    embodiment_tag: str,
    *,
    device: str = "cuda:0",
) -> Any:
    prepare_gr00t_n17_hub_env()
    import gr00t  # noqa: F401 — HF local-first / mistral patches
    _install_vlm_local_path_patches()
    import gr00t.model  # noqa: F401 — registers Gr00tN1d7
    from gr00t.data.embodiment_tags import EmbodimentTag
    from gr00t.policy.gr00t_policy import Gr00tPolicy

    return Gr00tPolicy(
        embodiment_tag=EmbodimentTag.resolve(embodiment_tag),
        model_path=str(checkpoint.expanduser().resolve()),
        device=device,
        strict=False,
    )


def _default_state_row(mod_key: str, dim: int) -> np.ndarray:
    """Placeholder proprio state safe for rot6d decode (identity pose, not all zeros)."""
    row = np.zeros(dim, dtype=np.float32)
    if mod_key == "eef_9d" and dim == 9:
        row[3:9] = _IDENTITY_ROT6D
    return row


def build_zero_state_dict(checkpoint: Path, embodiment_tag: str) -> dict[str, np.ndarray]:
    stats_path = checkpoint.expanduser().resolve() / "statistics.json"
    if not stats_path.is_file():
        raise FileNotFoundError(f"Missing statistics.json in checkpoint: {stats_path}")
    with stats_path.open(encoding="utf-8") as fh:
        stats = json.load(fh)
    if embodiment_tag not in stats:
        raise KeyError(
            f"embodiment_tag {embodiment_tag!r} not in {stats_path}; "
            f"available: {sorted(stats.keys())[:8]}..."
        )
    state_stats = stats[embodiment_tag]["state"]
    state_dict: dict[str, np.ndarray] = {}
    for mod_key, mod_stats in state_stats.items():
        dim = len(mod_stats["q01"])
        row = _default_state_row(mod_key, dim)
        state_dict[f"state.{mod_key}"] = row.reshape(1, 1, dim)
    return state_dict


def load_state_dict_from_path(
    state_path: Path | str | None,
    *,
    checkpoint: Path,
    embodiment_tag: str,
) -> dict[str, np.ndarray]:
    if not state_path:
        return build_zero_state_dict(checkpoint, embodiment_tag)
    path = Path(state_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"State file not found: {path}")
    data = np.load(path, allow_pickle=False)
    if isinstance(data, np.lib.npyio.NpzFile):
        state_dict: dict[str, np.ndarray] = {}
        for key in data.files:
            arr = np.asarray(data[key], dtype=np.float32)
            state_dict[key if key.startswith("state.") else f"state.{key}"] = arr
        if not state_dict:
            raise ValueError(f"Empty state npz: {path}")
        return state_dict
    arr = np.asarray(data, dtype=np.float32)
    zero = build_zero_state_dict(checkpoint, embodiment_tag)
    if arr.shape == (1, 1, 132) or arr.shape == (132,):
        flat = arr.reshape(-1)
        offset = 0
        merged: dict[str, np.ndarray] = {}
        for key, template in zero.items():
            dim = int(template.shape[-1])
            merged[key] = flat[offset : offset + dim].reshape(1, 1, dim).astype(np.float32)
            offset += dim
        return merged
    raise ValueError(
        f"Unsupported state array shape {arr.shape} in {path}; "
        "use .npz with state.* keys or a (1, 1, 132) vector"
    )


def parse_observation_gr00t(
    obs: dict[str, Any],
    modality_configs: dict[str, Any],
) -> dict[str, Any]:
    """Bundle-local copy of gr00t.eval.open_loop_eval.parse_observation_gr00t.

    Avoid importing open_loop_eval (pulls tyro/matplotlib/lerobot at module level).

    Raw ``obs`` values follow LeRobot step layout: video ``(T, H, W, C)``,
    state ``(T, D)``. A single RGB frame ``(H, W, C)`` is tiled to ``T``.
    """
    new_obs: dict[str, Any] = {}
    for modality in ("video", "state", "language"):
        new_obs[modality] = {}
        for key in modality_configs[modality].modality_keys:
            parsed_key = key if modality == "language" else f"{modality}.{key}"
            arr = obs[parsed_key]
            if isinstance(arr, str):
                new_obs[modality][key] = [[arr]]
                continue
            arr = np.asarray(arr)
            if modality == "video":
                horizon = len(modality_configs[modality].delta_indices)
                if arr.ndim == 3:
                    arr = np.stack([arr] * horizon, axis=0)
                elif arr.ndim != 4:
                    raise ValueError(
                        f"video.{key} must be (T, H, W, C) or (H, W, C); got {arr.shape}"
                    )
                if arr.shape[0] != horizon:
                    raise ValueError(
                        f"video.{key} horizon must be {horizon}; got T={arr.shape[0]}"
                    )
            elif modality == "state":
                horizon = len(modality_configs[modality].delta_indices)
                if arr.ndim == 3 and arr.shape[0] == 1:
                    # FlashRT state_dict uses (1, 1, D); Gr00tPolicy expects (T, D).
                    arr = arr.reshape(-1, arr.shape[-1])
                if arr.ndim != 2:
                    raise ValueError(
                        f"state.{key} must be (T, D); got {arr.shape}"
                    )
                if arr.shape[0] != horizon:
                    raise ValueError(
                        f"state.{key} horizon must be {horizon}; got T={arr.shape[0]}"
                    )
                arr = arr.astype(np.float32, copy=False)
            new_obs[modality][key] = arr[None, :]
    return new_obs


def build_obs_from_cli(
    policy: Any,
    *,
    prompt: str,
    image_paths: list[Path] | None,
    num_views: int,
    state_dict: dict[str, np.ndarray],
) -> dict[str, Any]:
    video_keys = list(policy.modality_configs["video"].modality_keys)
    lang_keys = list(policy.modality_configs["language"].modality_keys)
    if num_views > len(video_keys):
        raise ValueError(
            f"--num-views {num_views} exceeds embodiment video keys ({len(video_keys)}): "
            + ", ".join(video_keys)
        )

    if image_paths:
        images = load_images_from_paths(image_paths, num_views=num_views)
    else:
        images = placeholder_images(num_views)

    obs: dict[str, Any] = {}
    for key, value in state_dict.items():
        obs[key if key.startswith("state.") else f"state.{key}"] = value
    for idx, video_key in enumerate(video_keys[:num_views]):
        obs[f"video.{video_key}"] = images[idx]
    prompt_text = str(prompt or "")
    for lang_key in lang_keys:
        obs[lang_key] = prompt_text
    return parse_observation_gr00t(obs, policy.modality_configs)


def _install_aux_hooks(policy: Any, captured: dict[str, Any]) -> None:
    import torch

    lm = policy.model.backbone.model.model.language_model
    orig_lm_forward = lm.forward

    def lm_hook(self: Any, *fargs: Any, **fkwargs: Any) -> Any:
        if "inputs_embeds" in fkwargs:
            captured["llm_input_embeds"] = (
                fkwargs["inputs_embeds"].detach().to(torch.float32).cpu()
            )
        if "visual_pos_masks" in fkwargs:
            vpm = fkwargs["visual_pos_masks"]
            captured["visual_pos_masks"] = vpm.detach().cpu() if vpm is not None else None
        return orig_lm_forward(*fargs, **fkwargs)

    lm.forward = functools.partial(lm_hook, lm)

    ah = policy.model.action_head
    orig_gawf = ah.get_action_with_features

    def gawf_hook(self: Any, *args: Any, **kwargs: Any) -> Any:
        orig_randn = torch.randn

        def patched_randn(*ra: Any, **rkw: Any) -> Any:
            tensor = orig_randn(*ra, **rkw)
            if "initial_noise" not in captured:
                captured["initial_noise"] = tensor.detach().to(torch.float32).cpu().clone()
            return tensor

        torch.randn = patched_randn
        try:
            return orig_gawf(*args, **kwargs)
        finally:
            torch.randn = orig_randn

    ah.get_action_with_features = functools.partial(gawf_hook, ah)

    visual = policy.model.backbone.model.model.visual
    block0 = visual.blocks[0]

    def block0_pre_hook(_module: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        hidden = args[0] if args else kwargs.get("hidden_states")
        captured["pixel_features"] = hidden.detach().to(torch.float32).cpu()

    block0.register_forward_pre_hook(block0_pre_hook, with_kwargs=True)

    orig_visual_forward = visual.forward

    def visual_hook(self: Any, hidden_states: Any, grid_thw: Any, **kw: Any) -> Any:
        captured["grid_thw"] = grid_thw.detach().cpu()
        return orig_visual_forward(hidden_states, grid_thw, **kw)

    visual.forward = functools.partial(visual_hook, visual)

    rot = lm.rotary_emb
    orig_rot_forward = rot.forward

    def rot_hook(self: Any, x: Any, position_ids: Any) -> Any:
        cos, sin = orig_rot_forward(x, position_ids)
        captured["rope_cos"] = cos.detach().cpu()
        captured["rope_sin"] = sin.detach().cpu()
        return cos, sin

    rot.forward = functools.partial(rot_hook, rot)


def _run_policy_forward_for_aux(policy: Any, parsed_obs: dict[str, Any]) -> None:
    """Model forward only — aux hooks fire here; skip decode_action (needs valid pose)."""
    import torch
    from gr00t.data.types import MessageType
    from gr00t.policy.gr00t_policy import _rec_to_dtype

    unbatched_observations = policy._unbatch_observation(parsed_obs)
    processed_inputs = []
    for obs in unbatched_observations:
        vla_step_data = policy._to_vla_step_data(obs)
        messages = [{"type": MessageType.EPISODE_STEP.value, "content": vla_step_data}]
        processed_inputs.append(policy.processor(messages))
    collated_inputs = policy.collate_fn(processed_inputs)
    collated_inputs = _rec_to_dtype(collated_inputs, dtype=torch.bfloat16)
    with torch.inference_mode():
        policy.model.get_action(**collated_inputs)


def capture_aux(policy: Any, parsed_obs: dict[str, Any], *, seed: int = 0) -> dict[str, Any]:
    import torch

    captured: dict[str, Any] = {}
    _install_aux_hooks(policy, captured)
    torch.manual_seed(int(seed))
    np.random.seed(int(seed))
    with torch.inference_mode():
        _run_policy_forward_for_aux(policy, parsed_obs)
    missing = [key for key in _REQUIRED_AUX_KEYS if key not in captured]
    if missing:
        raise RuntimeError(f"Gr00tPolicy aux capture missing keys: {missing}")
    return {key: captured[key] for key in _REQUIRED_AUX_KEYS}


def release_policy(policy: Any) -> None:
    import torch

    del policy
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def preprocess_for_flashrt(
    checkpoint: Path,
    *,
    embodiment_tag: str,
    prompt: str,
    num_views: int,
    image_paths: list[Path] | None = None,
    state_path: Path | str | None = None,
    seed: int = 0,
    device: str = "cuda:0",
) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any], Any]:
    """Build obs, capture aux via Gr00tPolicy, return (aux, state_dict, policy)."""
    policy = load_gr00t_policy(checkpoint, embodiment_tag, device=device)
    state_dict = load_state_dict_from_path(
        state_path, checkpoint=checkpoint, embodiment_tag=embodiment_tag
    )
    parsed = build_obs_from_cli(
        policy,
        prompt=prompt,
        image_paths=image_paths,
        num_views=num_views,
        state_dict=state_dict,
    )
    aux = capture_aux(policy, parsed, seed=seed)
    return aux, state_dict, parsed, policy
