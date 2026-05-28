# Bench 日志摘要

报告：[`../../codeplan/bench_report_qwen_nvfp4.md`](../../codeplan/bench_report_qwen_nvfp4.md)

**GPU**：RTX PRO 5000 48GB · **12 轮 / skip 2**

---

## qwen3

```bash
QWEN3_MAX_Q_SEQ=0 bash scripts/bench_qwen_curl.sh --qwen3-only \
  --qwen3-long-tokens 1536 --rounds 12 --skip-first 2
```

| 场景 | TTFT | curl | decode tok/s |
|------|------|------|--------------|
| 短 | 1 ms | 546 ms | 125.6 |
| 长 1.5K | 41 ms | 644 ms | 114.0 |

workdir: `...-18101`

---

## qwen36 comparable（推荐对标）

```bash
export FLASHRT_QWEN36_LONG_KV_CACHE=fp8
export FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=512

QWEN36_MAX_SEQ=262208 QWEN36_PORT=8000 bash scripts/bench_qwen_curl.sh --qwen36-only \
  --profile comparable --qwen36-long-tokens 262144 --rounds 12 --skip-first 2
```

| 场景 | TTFT | curl | decode | route |
|------|------|------|--------|-------|
| 短 | 458 ms | 1.26 s | **83.8 tok/s** | short_spec |
| 长 | **81.4 s** | 82.9 s | **79.4 tok/s** | fp8_spec |

长测 rendered **218466** tokens（目标 262144，拟合预算内）。workdir: `...-20005`

---

## qwen36 stress（旧，repeat 中文）

长 262112 tokens · TTFT 110s · decode **63 tok/s** — 仅作压测参考，不宜对标 FlashRT 文档。
