# Bench 原始日志摘要

完整报告：[`../../codeplan/bench_report_qwen_nvfp4.md`](../../codeplan/bench_report_qwen_nvfp4.md)

**GPU**：NVIDIA RTX PRO 5000（Blackwell / SM120）  
规则：`--rounds 12 --skip-first 2`（后 10 轮均值）

---

## qwen3

```bash
QWEN3_MAX_Q_SEQ=0 bash scripts/bench_qwen_curl.sh --qwen3-only \
  --qwen3-long-tokens 1536 --rounds 12 --skip-first 2
```

| 场景 | curl | decode tok/s | prefill |
|------|------|--------------|---------|
| 短 | 546 ms | **125.6** | 1.0 ms |
| 长 1.5K | 644 ms | **114.0** | 41.1 ms |

workdir: `/tmp/flashcli-bench-qwen-18101`

---

## qwen36

```bash
flashcli serve qwen36-27b-nvfp4 --port 8000 --K 6 --max-seq 262208 --warmup-preset auto

QWEN36_MAX_SEQ=262208 QWEN36_PORT=8000 bash scripts/bench_qwen_curl.sh --qwen36-only \
  --qwen36-long-tokens 262144 --rounds 12 --skip-first 2
```

| 场景 | curl | decode tok/s | prefill | prompt |
|------|------|--------------|---------|--------|
| 短 | 1.26 s | **83.9** | 457 ms | 19 |
| 长 256K | **112.0 s** | **63.0** | **110.4 s** | 262112† |

†拟合：`rendered=262112`，`seq_slack=32`，`max-seq=262208`

workdir: `/tmp/flashcli-bench-qwen-19553`
