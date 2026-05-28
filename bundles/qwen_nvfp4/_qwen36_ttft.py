"""Local true TTFT (prefill → first token) for Qwen36 without editing FlashRT.

Calls the same installed ``flash_rt`` frontend methods the server uses, then
stops before the speculative decode loop.
"""

from __future__ import annotations

import os
import time
from typing import Any

import torch


def _long_ctx_first_token(fe: Any, input_ids: torch.Tensor, *, K: int) -> tuple[torch.Tensor, str]:
    """Mirror ``_generate_long_ctx_speculative_KN_nvfp4`` through first token."""
    from flash_rt import flash_rt_kernels as fvk

    prompt_len = int(input_ids.shape[1])
    hidden = fe._cfg["hidden_size"]
    tq_spec_k = os.environ.get("FLASHRT_QWEN36_TQ_SPEC_K", "")
    if tq_spec_k:
        K = int(tq_spec_k)
    else:
        K = fe._long_tq_effective_k(prompt_len, K)
    use_kernel_accept = os.environ.get("FLASHRT_QWEN36_KERNEL_ACCEPT", "1") == "1"
    accept_parts = int(os.environ.get("FLASHRT_QWEN36_ACCEPT_PARTS", "32") or "32")
    use_partitioned_accept = (
        use_kernel_accept
        and accept_parts > 1
        and hasattr(fvk, "qwen36_spec_accept_partitioned_bf16")
        and hasattr(fe, "_spec_argmax_partial_vals")
    )

    s = torch.cuda.current_stream().cuda_stream
    fvk.gpu_copy(
        fe._gen_out_buf[:, :prompt_len].data_ptr(),
        input_ids.data_ptr(),
        prompt_len * 8,
        s,
    )
    last_h, last_logits = fe._prefill_long_ctx_tq_chunked(input_ids)
    if use_kernel_accept:
        if use_partitioned_accept:
            fvk.qwen36_spec_accept_partitioned_bf16(
                last_logits.data_ptr(),
                fe._spec_argmax_buf.data_ptr(),
                fe._spec_argmax_buf.data_ptr(),
                fe._spec_accept_n_buf.data_ptr(),
                fe._spec_argmax_partial_vals.data_ptr(),
                fe._spec_argmax_partial_idx.data_ptr(),
                1,
                fe._cfg["vocab_size"],
                0,
                accept_parts,
                s,
            )
        else:
            fvk.qwen36_spec_accept_greedy_bf16(
                last_logits.data_ptr(),
                fe._spec_argmax_buf.data_ptr(),
                fe._spec_argmax_buf.data_ptr(),
                fe._spec_accept_n_buf.data_ptr(),
                1,
                fe._cfg["vocab_size"],
                0,
                s,
            )
        tok = fe._spec_argmax_buf[:1].view(1, 1)
    else:
        tok = last_logits.argmax(dim=-1, keepdim=True).view(1, 1)

    cur_pos = prompt_len
    mtp_tail = fe._long_mtp_prefill_tail_for_prompt(prompt_len)
    mtp_base = 0
    if mtp_tail > 0:
        first = max(1, prompt_len - mtp_tail)
        tail_start = int(getattr(fe, "_long_mtp_h_tail_start", first - 1))
        tail_h = fe._long_mtp_h_tail
        used_kv_only = False
        if os.environ.get("FLASHRT_QWEN36_LONG_MTP_TAIL_KV_ONLY", "1") == "1":
            rows = prompt_len - first
            h_start = (first - 1) - tail_start
            used_kv_only = fe._prefill_mtp_tail_kv_nvfp4(
                tail_h[h_start : h_start + rows],
                input_ids[:, first:prompt_len].view(-1),
                first,
                mtp_base,
            )
            if used_kv_only:
                mtp_base += rows
        if not used_kv_only:
            for p in range(first, prompt_len):
                h_idx = (p - 1) - tail_start
                prev_h_p = tail_h[h_idx : h_idx + 1].view(1, 1, hidden).contiguous()
                prev_tok_p = input_ids[:, p : p + 1]
                fe.forward_mtp_head_nvfp4(
                    prev_h_p, prev_tok_p, p, mtp_cache_pos=mtp_base
                )
                mtp_base += 1
    fe.forward_mtp_head_nvfp4(last_h, tok, cur_pos, mtp_cache_pos=mtp_base)
    route = f"{getattr(fe, '_long_kv_cache_mode', 'tq')}_spec"
    return tok, route


def _short_ctx_first_token(fe: Any, input_ids: torch.Tensor) -> tuple[torch.Tensor, str]:
    """Mirror short ``generate_own_speculative_KN_nvfp4`` prefill + MTP seed."""
    prompt_len = int(input_ids.shape[1])
    hidden = fe._cfg["hidden_size"]
    gs_pf = fe._graph_stream
    for p in range(prompt_len):
        fe._static_token_id.copy_(input_ids[:, p : p + 1])
        g_pf = fe._ensure_graph_for_pos_nvfp4(p)
        gs_pf.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(gs_pf):
            g_pf.replay()
        torch.cuda.current_stream().wait_stream(gs_pf)
        fe._prefill_h_cache[p : p + 1].copy_(fe._last_hidden_buf.view(1, hidden))
    tok = fe._logits_buf.argmax(dim=-1, keepdim=True).view(1, 1)
    for p in range(1, prompt_len):
        prev_h_p = fe._prefill_h_cache[p - 1 : p].view(1, 1, hidden).contiguous()
        prev_tok_p = input_ids[:, p : p + 1]
        fe.forward_mtp_head_nvfp4(prev_h_p, prev_tok_p, p)
    h_last_prompt = fe._prefill_h_cache[prompt_len - 1 : prompt_len].view(
        1, 1, hidden
    ).contiguous()
    fe.forward_mtp_head_nvfp4(h_last_prompt, tok, prompt_len)
    return tok, "short_spec"


def measure_prefill_ttft(
    fe: Any,
    input_ids: torch.Tensor,
    *,
    max_new_tokens: int = 64,
    K: int = 6,
) -> dict[str, Any]:
    """Time from reset to first output token (prefill + MTP tail; no decode loop)."""
    if input_ids.device.type != "cuda":
        input_ids = input_ids.cuda()
    prompt_len = int(input_ids.shape[1])
    use_long = bool(
        getattr(fe, "_long_ctx_mode", False)
        and fe._should_use_long_ctx_route(prompt_len, max_new_tokens)
        and fe._weights.ptrs.get("mtp") is not None
    )

    fe.reset_state()
    fe.reset_mtp_state()
    if not hasattr(fe, "_rope_cos_table"):
        fe._build_rope_table()

    ev_pf0 = torch.cuda.Event(enable_timing=True)
    ev_pf1 = torch.cuda.Event(enable_timing=True)
    torch.cuda.synchronize()
    t0_wall = time.perf_counter()
    ev_pf0.record()

    with torch.no_grad():
        if use_long:
            tok, route = _long_ctx_first_token(fe, input_ids, K=K)
        elif fe._weights.ptrs.get("mtp") is not None:
            tok, route = _short_ctx_first_token(fe, input_ids)
        else:
            raise RuntimeError("MTP head not loaded — cannot measure spec TTFT")

    ev_pf1.record()
    torch.cuda.synchronize()
    engine_prefill_ms = float(ev_pf0.elapsed_time(ev_pf1))
    client_ttft_ms = (time.perf_counter() - t0_wall) * 1000.0
    tok_id = int(tok.view(-1).item())
    first_text = fe._tokenizer.decode([tok_id], skip_special_tokens=False)

    return {
        "prompt_tokens": prompt_len,
        "route": route,
        "first_token_id": tok_id,
        "first_token_text": first_text,
        "engine_prefill_ms": engine_prefill_ms,
        "client_ttft_ms": client_ttft_ms,
        "max_new_tokens": int(max_new_tokens),
        "K": int(K),
    }
