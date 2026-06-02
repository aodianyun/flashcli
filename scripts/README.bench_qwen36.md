# Qwen3.6-27B NVFP4 性能对比（唯一入口）

在 **同一张 GPU、同一套 NVFP4 权重、同一套 HTTP payload** 上对比：

| 臂 | 服务 | 权重 |
|----|------|------|
| **FlashRT** | `flashcli serve qwen36-27b-nvfp4` | `~/.flashcli/models/qwen36-27b-nvfp4/checkpoint` |
| **vLLM** | `vllm serve`（同目录） | 同上（`--vllm-checkpoint` 可覆盖） |

**入口脚本**：`scripts/bench_qwen36_compare.sh`  
**报告**：`OUT_DIR/REPORT.md` + `report.json`（默认 `OUT_DIR=/tmp/qwen36-bench-nvfp4-<时间戳>`）

---

## 脚本结构

```
bench_qwen36_compare.sh          ← 唯一编排
├── bench_qwen_curl.sh           HTTP 多轮压测
├── bench_qwen_curl_stream.py
├── bench_qwen_make_payload.py   长上下文 payload
├── bench_qwen36_serve_metrics.py
└── bench_qwen36_report.py       REPORT.md
```

---

## 上下文范围（四选一）

| 用法 | 含义 |
|------|------|
| `--short-only` | 仅短上下文（`qwen36_short`） |
| `--long-only` | 仅长上下文（`qwen36_long`） |
| `--long-tokens N` | 长 prompt 目标 token 数（配合 long 或 comparable） |
| （默认 / `--comparable`） | **短 + 长** 都跑 |

指定窗口：`--max-seq N`（FlashRT serve；长 payload 拟合；vLLM 在 48GB 上仍可能 cap 到 16384）。

---

## 一键命令

### 环境（一次性）

```bash
cd /app/flashcli
flashcli pull qwen36-27b-nvfp4 --bundle bundles/qwen_nvfp4
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"

pip install -U vllm
pip uninstall -y flash-attn
pip install 'kernels>=0.12,<0.13'
```

长测 FlashRT（与 codeplan 一致）：

```bash
export FLASHRT_QWEN36_LONG_KV_CACHE=fp8
export FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=512
```

### 1. 冒烟 — 短上下文

```bash
bash scripts/bench_qwen36_compare.sh --quick
# 仅短测、3 轮；默认只跑 FlashRT+vLLM 若未加 --flashcli-only
```

### 2. 正式 — 短 + 长（双臂对比）

```bash
bash scripts/bench_qwen36_compare.sh --comparable
# OUT=/tmp/qwen36-bench-nvfp4-.../REPORT.md
```

### 3. 仅短 / 仅长 / 自定义长上下文

```bash
# 仅短（12 轮，丢前 2）
bash scripts/bench_qwen36_compare.sh --short-only --rounds 12 --skip-first 2

# 仅长 256K（FlashRT；vLLM 在 48GB 上建议 --pytorch-only 跳过或 --short-only）
bash scripts/bench_qwen36_compare.sh --long-only --comparable --flashcli-only

# 自定义长上下文，例如 128K
bash scripts/bench_qwen36_compare.sh --long-only --long-tokens 131072 --max-seq 131072 \
  --rounds 12 --skip-first 2

# 短+长但长 prompt 用 64K
bash scripts/bench_qwen36_compare.sh --long-tokens 65536 --max-seq 65536
```

### 4. 分步跑同一 OUT_DIR 再汇总

```bash
OUT=/tmp/qwen36-bench-nvfp4-manual
bash scripts/bench_qwen36_compare.sh --flashcli-only --short-only --out-dir "$OUT" --rounds 12 --skip-first 2
bash scripts/bench_qwen36_compare.sh --pytorch-only  --short-only --out-dir "$OUT" --rounds 12 --skip-first 2
bash scripts/bench_qwen36_compare.sh --report-only --out-dir "$OUT"
```

### 5. 可选 FP8 vLLM 对照（不同权重）

```bash
bash scripts/bench_qwen36_compare.sh --pytorch-only --short-only \
  --vllm-checkpoint ~/.flashcli/models/qwen36-27b-fp8/checkpoint \
  --vllm-model-name qwen3.6-27b-fp8
```

---

## 常用参数

| 参数 | 含义 |
|------|------|
| `--comparable` | 短+长；12 轮 skip 2；warmup auto；max_seq 262208 |
| `--quick` | 仅短；3 轮 skip 1 |
| `--short-only` / `--long-only` | 只跑一种 case |
| `--long-tokens N` | 长 prompt user tokens |
| `--flashcli-only` / `--pytorch-only` | 单臂 |
| `--report-only` | 仅从已有 workdir 生成报告 |
| `--out-dir DIR` | 工作根目录 |
| `--checkpoint` | NVFP4 权重（FlashRT + 默认 vLLM） |

---

## 故障速查

| 现象 | 处理 |
|------|------|
| vLLM `flash_attn_2_cuda` | `pip uninstall -y flash-attn` |
| vLLM `kernels` / transformers 崩 | `pip install 'kernels>=0.12,<0.13'` |
| vLLM OOM | `--short-only` 或 `VLLM_MAX_MODEL_LEN=8192` |
| vLLM 长测 256K | 48GB 通常不可行；长测用 `--flashcli-only` |
| decode n/a | 看 `*/serve.log`，确认 `completion_tokens≈64` |

---

## 修订原则

1. 只改 `bench_qwen36_compare.sh` 做编排  
2. HTTP 压测只改 `bench_qwen_curl.sh` / `bench_qwen_curl_stream.py`  
3. 基线仅 **vLLM**（已移除 transformers hf-server）
