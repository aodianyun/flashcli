# Qwen NVFP4 Bench 原始日志

完整报告见：[`../../codeplan/bench_report_qwen_nvfp4.md`](../../codeplan/bench_report_qwen_nvfp4.md)

统计规则：`--rounds 12 --skip-first 2`（后 10 轮平均）

---

## qwen3

```text
QWEN3_MAX_Q_SEQ=0 bash scripts/bench_qwen_curl.sh --qwen3-only \
  --qwen3-long-tokens 1536 --rounds 12 --skip-first 2
workdir=/tmp/flashcli-bench-qwen-18101
```

**短上下文 mean**：curl 546ms · tok_per_s **125.6** · prefill 1.0ms · decode 509.6ms

**长上下文 mean**：curl 644ms · prompt 1544 · tok_per_s **114.0** · prefill 41.1ms

<details>
<summary>完整终端输出</summary>

```text
[bench-qwen]   round 1/12 (warmup, excluded): curl_wall=561ms tok_per_s=124.8
...
━━ qwen3 short ctx (mean of 10 rounds, skipped first 2) ━━
  usage (mean): curl_wall_ms_mean=546 prompt_tokens=15 completion_tokens=64 prefill_ms=1.0 decode_ms=509.6 wall_s=0.5 tok_per_s=125.6
...
━━ qwen3 long ctx (prompt≈1536) (mean of 10 rounds, skipped first 2) ━━
  usage (mean): curl_wall_ms_mean=644 prompt_tokens=1544 completion_tokens=64 prefill_ms=41.1 decode_ms=561.5 wall_s=0.6 tok_per_s=114.0
```

</details>

---

## qwen36

```text
QWEN36_PORT=8000 bash scripts/bench_qwen_curl.sh --qwen36-only \
  --qwen36-long-tokens 32768 --rounds 12 --skip-first 2
workdir=/tmp/flashcli-bench-qwen-18530
```

**短上下文 mean**：curl **1261ms** · wall_s **1.2s** · e2e **~53.3 tok/s**（64/1.2）

**长上下文 mean**：curl **6179ms** · prompt **32780** · wall_s **6.1s** · e2e **~10.5 tok/s**（64/6.1）

> qwen36 响应 `usage` 未含 `tok_per_s`/`prefill_ms`；上表 e2e 由 `wall_s` 推算。

<details>
<summary>完整终端输出</summary>

```text
[bench-qwen]   round 1/12 (warmup, excluded): curl_wall=4837ms tok_per_s=n/a
[bench-qwen]   round 2/12 (warmup, excluded): curl_wall=1263ms tok_per_s=n/a
[bench-qwen]   round 3/12: curl_wall=1261ms tok_per_s=n/a
...
━━ qwen36 short ctx (mean of 10 rounds, skipped first 2) ━━
  usage (mean): curl_wall_ms_mean=1261 prompt_tokens=19 completion_tokens=64 wall_s=1.2
...
[bench-qwen]   round 1/12 (warmup, excluded): curl_wall=12197ms tok_per_s=n/a
[bench-qwen]   round 2/12 (warmup, excluded): curl_wall=6059ms tok_per_s=n/a
[bench-qwen]   round 3/12: curl_wall=6091ms tok_per_s=n/a
...
[bench-qwen]   round 12/12: curl_wall=6239ms tok_per_s=n/a
━━ qwen36 long ctx (prompt≈32768) (mean of 10 rounds, skipped first 2) ━━
  usage (mean): curl_wall_ms_mean=6179 prompt_tokens=32780 completion_tokens=64 wall_s=6.1
```

</details>
