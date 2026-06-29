"""Qwen3-VL frontend subclass — tools= support without modifying FlashRT."""

from __future__ import annotations

import json
import os
from typing import Any

from flash_rt.frontends.torch._qwen3_vl_vision_rtx import Qwen3VlVisionRtx
from flash_rt.frontends.torch.qwen3_rtx import Qwen3TorchFrontendRtx
from flash_rt.frontends.torch.qwen3_vl_rtx import (
    Qwen3VlTorchFrontendRtx,
    _require_qwen3_vl_kernels,
)

from _qwen3_vl_util_messages import (
    DEFAULT_VL_PROCESSOR_REPOS,
    configure_vl_max_pixels,
    extract_images_from_messages,
    has_image_processor,
    load_qwen3_vl_processor,
    qwen3_vl_transformers_version_error,
    resolve_processor_tokenizer,
    vl_processor_call_kwargs,
)


def _require_flash_rt_kernels_for_vl(device: str = "cuda:0") -> None:
    """SM120 ViT bf16 linears need ``w16a16_gemm_sm120_bf16`` in flash_rt_kernels."""
    import torch
    from flash_rt import flash_rt_kernels as fvk

    dev = torch.device(device)
    if dev.type != "cuda" or not torch.cuda.is_available():
        return
    major, minor = torch.cuda.get_device_capability(dev)
    if major * 10 + minor < 120:
        return
    if hasattr(fvk, "w16a16_gemm_sm120_bf16"):
        return
    raise RuntimeError(
        "flash_rt_kernels is missing w16a16_gemm_sm120_bf16 (Qwen3-VL vision on "
        "SM120). Rebuild native libs with FlashRT "
        "-DFLASHRT_ENABLE_QWEN35MOE=ON — run "
        "bundles/qwen3_vl_nvfp4/build.sh, then pack again."
    )


class Qwen3VlFrontend(Qwen3VlTorchFrontendRtx):
    """Adds optional ``tools`` and a separate ``max_q_seq`` prefill budget.

    FlashRT's ``Qwen3VlTorchFrontendRtx`` passes ``max_q_seq=max_seq``, which
    sizes prefill scratch (including ``_logits_buf``) for the full KV budget.
    On 16GB GPUs that OOMs at the default ``max_seq=4096``. This subclass
    keeps ``max_seq`` for KV only and uses a smaller ``max_q_seq`` for prefill.
    """

    def __init__(
        self,
        checkpoint_path: str,
        *,
        device: str = "cuda:0",
        max_seq: int = 2048,
        max_q_seq: int = 1024,
        max_pixels: int | None = None,
        processor_fallback_repos: tuple[str, ...] | None = None,
    ) -> None:
        max_seq = int(max_seq)
        max_q_seq = int(max_q_seq)
        if max_q_seq > max_seq:
            raise ValueError(
                f"max_q_seq ({max_q_seq}) cannot exceed max_seq ({max_seq})"
            )

        self.checkpoint_path = str(checkpoint_path)
        self.device = device
        self.max_seq = max_seq
        self.max_q_seq = max_q_seq
        self._processor_fallback_repos = (
            processor_fallback_repos
            if processor_fallback_repos is not None
            else DEFAULT_VL_PROCESSOR_REPOS
        )

        _require_qwen3_vl_kernels()
        _require_flash_rt_kernels_for_vl(device)

        cfg = json.load(open(os.path.join(checkpoint_path, "config.json")))
        self._image_token_id = int(cfg["image_token_id"])
        self._video_token_id = int(cfg["video_token_id"])
        self._vision_start_token_id = int(cfg["vision_start_token_id"])
        vc = cfg["vision_config"]
        self._merge = int(vc["spatial_merge_size"])
        self._vis_head_dim = vc["hidden_size"] // vc["num_heads"]
        self._num_grid_per_side = int(vc["num_position_embeddings"] ** 0.5)
        self._deepstack_layers = len(vc["deepstack_visual_indexes"])
        self._rope_theta = float(cfg["rope_theta"])
        self._head_dim = int(cfg["head_dim"])
        self._mrope_section = tuple(cfg["rope_scaling"]["mrope_section"])
        eos = cfg.get("eos_token_id")
        if eos is None:
            self._eos_token_ids: set[int] = set()
        else:
            self._eos_token_ids = set(eos if isinstance(eos, list) else [eos])

        self.llm = Qwen3TorchFrontendRtx(
            checkpoint_path,
            device=device,
            max_seq=max_seq,
            max_q_seq=max_q_seq,
        )
        self.vision = Qwen3VlVisionRtx(checkpoint_path, device=device)
        self.processor = load_qwen3_vl_processor(
            checkpoint_path,
            fallback_repos=self._processor_fallback_repos,
        )
        self.max_pixels = max_pixels
        configure_vl_max_pixels(self.processor, max_pixels)

        self._prompt: dict[str, Any] | None = None
        self._decode_graphs: dict[int, Any] = {}
        self._prefill_graphs: dict = {}
        self._pg_buffers: dict = {}
        import torch as _torch

        hidden = self.llm._cfg["hidden_size"]
        vocab = self.llm._cfg["vocab_size"]
        self._pg_last_hidden = _torch.empty(
            self.max_seq, hidden, dtype=_torch.bfloat16, device=device
        )
        self._pg_logits = _torch.empty(1, vocab, dtype=_torch.bfloat16, device=device)

    @property
    def tokenizer(self) -> Any:
        return resolve_processor_tokenizer(self.processor)

    def _apply_vl_chat_template(
        self,
        messages: list,
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        """Build multimodal inputs; pass max_pixels so vision tokens stay within budget."""
        configure_vl_max_pixels(self.processor, self.max_pixels)
        pixel_kw = vl_processor_call_kwargs(self.max_pixels)

        images = extract_images_from_messages(messages)
        if images:
            if not has_image_processor(self.processor):
                self.processor = load_qwen3_vl_processor(
                    self.checkpoint_path,
                    fallback_repos=self._processor_fallback_repos,
                )
                configure_vl_max_pixels(self.processor, self.max_pixels)
            if not has_image_processor(self.processor):
                ver_err = qwen3_vl_transformers_version_error()
                if ver_err is not None:
                    raise RuntimeError(ver_err)
                raise RuntimeError(
                    "Multimodal inference requires a Qwen3-VL processor with "
                    "image_processor. Checkpoint has preprocessor sidecars but "
                    f"processor load failed (fallback repos: {list(self._processor_fallback_repos)!r}). "
                    "Ensure transformers>=4.57.0 in the bundle runtime, install torchvision, "
                    "or set QWEN3_VL_PROCESSOR_REPO / HF_ENDPOINT for processor download."
                )

            template_kw: dict[str, Any] = {
                "add_generation_prompt": True,
                "tokenize": False,
            }
            if tools is not None:
                template_kw["tools"] = tools
            text = self.processor.apply_chat_template(messages, **template_kw)
            inputs = self.processor(
                images=images,
                text=text,
                return_tensors="pt",
                padding=True,
                **pixel_kw,
            ).to(self.device)
            if inputs.get("pixel_values") is None or inputs.get("image_grid_thw") is None:
                raise RuntimeError(
                    "Failed to build vision tensors (pixel_values / image_grid_thw). "
                    "Try: pip install torchvision"
                )
            return inputs

        template_kw = {
            "add_generation_prompt": True,
            "tokenize": True,
            "return_dict": True,
            "return_tensors": "pt",
        }
        if tools is not None:
            template_kw["tools"] = tools
        return self.processor.apply_chat_template(messages, **template_kw).to(self.device)

    def set_prompt(self, messages: list, *, tools: list[dict[str, Any]] | None = None) -> None:
        import torch

        from flash_rt.frontends.torch import _qwen3_vl_geometry as geo

        inputs = self._apply_vl_chat_template(messages, tools=tools)
        input_ids = inputs["input_ids"][0]
        s_len = int(input_ids.shape[0])
        if s_len > self.max_seq:
            hint = ""
            if inputs.get("pixel_values") is not None or inputs.get("pixel_values_videos") is not None:
                hint = (
                    f" Lower --max-pixels (now {self.max_pixels}) or raise "
                    f"--max-seq / --max-q-seq."
                )
            raise ValueError(
                f"prompt length {s_len} exceeds max_seq {self.max_seq}.{hint}"
            )
        if s_len > self.max_q_seq:
            raise ValueError(
                f"prompt length {s_len} exceeds max_q_seq {self.max_q_seq} "
                f"(prefill scratch); increase --max-q-seq or reduce --max-pixels"
            )

        merge = self._merge
        image_grid = inputs.get("image_grid_thw")
        video_grid = inputs.get("video_grid_thw")
        pix_img = inputs.get("pixel_values")
        pix_vid = inputs.get("pixel_values_videos")
        if pix_img is not None:
            pix_img = pix_img.to(torch.bfloat16)
        if pix_vid is not None:
            pix_vid = pix_vid.to(torch.bfloat16)

        if pix_img is None and pix_vid is None:
            ids_list = input_ids.tolist()
            if (
                self._image_token_id not in ids_list
                and self._video_token_id not in ids_list
            ):
                self._prompt = {
                    "text_only": True,
                    "input_ids": input_ids,
                    "S": s_len,
                    "mrope_max": s_len - 1,
                    "pg_key": None,
                }
                return

        segs = geo.vision_segments(
            input_ids.cpu(),
            image_grid,
            video_grid,
            image_token_id=self._image_token_id,
            video_token_id=self._video_token_id,
            spatial_merge_size=merge,
        )
        seg_pix: list = []
        seg_grids: list = []
        spans: list[tuple[int, int]] = []
        seg_patches: list[int] = []
        off_img = off_vid = 0
        for sg in segs:
            npp = sg["patches"]
            if sg["kind"] == "image":
                if pix_img is None:
                    raise RuntimeError(
                        "Vision segment requires pixel_values but none were produced."
                    )
                seg_pix.append(pix_img[off_img : off_img + npp])
                off_img += npp
            else:
                seg_pix.append(pix_vid[off_vid : off_vid + npp])
                off_vid += npp
            seg_grids.append(sg["grid"])
            spans.append(sg["span"])
            seg_patches.append(npp)

        seg_grid = torch.tensor(seg_grids, dtype=torch.long)
        pixel_values = torch.cat(seg_pix, dim=0).contiguous()

        pos_ids = geo.mrope_position_ids(
            input_ids.cpu(),
            image_grid.cpu() if image_grid is not None else None,
            video_grid.cpu() if video_grid is not None else None,
            image_token_id=self._image_token_id,
            video_token_id=self._video_token_id,
            vision_start_token_id=self._vision_start_token_id,
            spatial_merge_size=merge,
        )
        mcos, msin = geo.mrope_cos_sin(
            pos_ids,
            head_dim=self._head_dim,
            rope_theta=self._rope_theta,
            mrope_section=self._mrope_section,
            device=self.device,
        )
        vcos, vsin = geo.vision_rope_cos_sin(
            seg_grid,
            head_dim=self._vis_head_dim,
            spatial_merge_size=merge,
            device=self.device,
        )
        pos_embeds = geo.vision_pos_embeds(
            seg_grid,
            self.vision.pos_embed,
            num_grid_per_side=self._num_grid_per_side,
            spatial_merge_size=merge,
            device=self.device,
        )

        self._prompt = {
            "input_ids": input_ids,
            "pixel_values": pixel_values,
            "spans": spans,
            "seg_patches": seg_patches,
            "img_start": spans[0][0],
            "img_end": spans[0][1],
            "mcos": mcos,
            "msin": msin,
            "vcos": vcos,
            "vsin": vsin,
            "pos_embeds": pos_embeds,
            "S": s_len,
            "mrope_max": int(pos_ids.max()),
        }
        if len(spans) == 1:
            self._prompt["pg_key"] = self._stage_prefill_inputs(
                seg_patches[0], s_len, spans[0]
            )

    def prefill_graph(self):
        if self._prompt is None:
            raise RuntimeError("call set_prompt() before prefill_graph()")
        if self._prompt.get("text_only"):
            llm = self.llm
            llm.reset_state()
            ids = self._prompt["input_ids"].view(1, -1)
            return llm.prefill_with_graph(ids)
        self.llm.reset_state()
        return super().prefill_graph()

    def warmup_decode_graphs(self, n_tokens: int) -> None:
        if self._prompt is None:
            raise RuntimeError("call set_prompt() before warmup")
        if self._prompt.get("text_only"):
            start = int(self._prompt["S"])
            for i in range(n_tokens):
                self.llm._ensure_decode_graph(start + i)
            return
        super().warmup_decode_graphs(n_tokens)

    def _decode_step_graph(self, token: int, cache_pos: int, rope_pos: int):
        if self._prompt and self._prompt.get("text_only"):
            llm = self.llm
            llm._static_token_id.fill_(int(token))
            llm._ensure_decode_graph(cache_pos).replay()
            return llm._logits_buf[:1]
        return super()._decode_step_graph(token, cache_pos, rope_pos)
