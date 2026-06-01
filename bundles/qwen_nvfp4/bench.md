# Bench log summary

**GPU**: RTX PRO 5000 48GB · **12 rounds / skip first 2**

## qwen3-8b-nvfp4

| Scenario | TTFT | curl | decode tok/s |
|----------|------|------|--------------|
| short | 1 ms | 546 ms | 125.6 |
| long 1.5K | 41 ms | 644 ms | 114.0 |

## Local TTFT (no HTTP)

`scripts/bench_qwen36_ttft_local.py` — prefill-only probe without HTTP (see script `--help`).

## Default `stream=true`

- **qwen3**: true SSE; `client_ttft_ms` = first content chunk
- **qwen36**: true SSE via FlashRT ``qwen36_agent`` committed-stream decode; ``client_ttft_ms`` = first content chunk (token-level EOS/KV rollback in frontend)

Disable streaming: `bash scripts/bench_qwen_curl.sh --no-stream …`

## qwen36 comparable (full ~256K — recommended baseline)

```bash
bash scripts/bench_qwen_curl.sh --qwen36-only --qwen36-long-tokens 262112 \
  --qwen36-long-prompt-style flashrt --rounds 12 --skip-rounds 2
```

| Scenario | prompt | TTFT | curl | decode | route |
|----------|--------|------|------|--------|-------|
| short | 19 | 457 ms | 1.26 s | **83.7 tok/s** | short_spec |
| long | **262103** | **110.6 s** | 112.4 s | **69.2 tok/s** | fp8_spec |

## Historical (do not compare to FlashRT docs directly)

- **~218K comparable** (under-filled payload): decode 79.4 tok/s
- **stress repeat**: decode 63 tok/s — stress test only
