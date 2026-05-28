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

## 本地真 TTFT（无 HTTP）

`scripts/bench_qwen36_ttft_local.py` — 见 [`../../codeplan/test.md`](../../codeplan/test.md) 中「qwen36 本地真 TTFT」一节。

---

## Bench 默认 `stream=true`

- **qwen3**：真 SSE，`client_ttft_ms` = 首个 content chunk（本地无网络时≈`server_ttft_ms`）
- **qwen36**：伪流式（整段算完再一次吐），看 **`server_ttft_ms`**；`client_ttft_ms`≈整请求墙钟

关闭流式：`bash scripts/bench_qwen_curl.sh --no-stream …`

## qwen36 comparable（满 256K · 推荐对标）

```bash
export FLASHRT_QWEN36_LONG_KV_CACHE=fp8
export FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=512

QWEN36_MAX_SEQ=262208 QWEN36_PORT=8000 bash scripts/bench_qwen_curl.sh --qwen36-only \
  --profile comparable --qwen36-long-tokens 262144 --rounds 12 --skip-first 2
```

| 场景 | prompt | TTFT | curl | decode | route |
|------|--------|------|------|--------|-------|
| 短 | 19 | 457 ms | 1.26 s | **83.7 tok/s** | short_spec |
| 长 | **262103** | **110.6 s** | 112.4 s | **69.2 tok/s** | fp8_spec |

workdir: `...-21495`（2026-05-28）

---

## qwen36 comparable 旧（~218K，拟合未打满）

长 rendered **218466** · TTFT 81.4 s · decode **79.4 tok/s** — workdir `...-20005`，仅作历史对比。

---

## qwen36 stress（旧，repeat 中文）

长 262112 tokens · TTFT 110s · decode **63 tok/s** — 压测参考，不宜对标 FlashRT 文档。
