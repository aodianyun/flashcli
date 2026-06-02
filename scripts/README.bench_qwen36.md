# Qwen3.6 性能对比（唯一入口）

## 目标（只推进这一件事）

在 **同一张 GPU、同一套 HTTP 请求** 上，对比两条推理臂：

| 臂 | 权重 | 服务 | 角色 |
|----|------|------|------|
| **A. FlashRT** | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) + MTP | `flashcli serve` | 产品路径 |
| **B. 基线** | **同一份 NVFP4**（默认与 A 相同目录） | **vLLM**（推荐） | 同权重、比推理引擎 |

可选：B 臂改用 [Qwen3.6-27B-FP8](https://www.modelscope.cn/models/Qwen/Qwen3.6-27B-FP8)（`--hf-checkpoint`）做「官方 FP8 + vLLM」对照，**不是**同权重引擎对比。

**不要**用 NVFP4 跑 `bench_qwen36_hf_server.py`（`--hf-server` 兜底）；那条路径会 partial load / 空生成。

---

## 脚本分工（只记 1 个入口 + 4 个支撑）

```
bench_qwen36_compare.sh     ← 唯一编排：起服务 → HTTP 压测 → 报告
├── bench_qwen_make_payload.py   生成长上下文 JSON
├── bench_qwen_curl.sh             多轮 HTTP（stream=true）
│   └── bench_qwen_curl_stream.py  单轮流式 + 客户端计时
├── bench_qwen36_serve_metrics.py  从 serve.log 补引擎 timing（FlashRT / HF 日志）
└── bench_qwen36_report.py         汇总 REPORT.md

可选、不参与主流程：
├── bench_qwen36_hf_server.py      最小 transformers 服务（仅 --hf-server）
├── bench_qwen36_ttft_local.py      本地 TTFT 探针（无 HTTP）
└── bench_qwen36_run_flashrt_server.py  旧 FlashRT 直连（已不用）
```

---

## 指标怎么读（避免再混）

| 字段 | 来源 | 用途 |
|------|------|------|
| **decode tok/s** | 优先 `usage.decode_tok_per_s` 或 serve.log 引擎行 | **横向对比主指标**（对齐 codeplan ~83.7 短测） |
| **TTFT ms** | `usage.ttft_ms` / log `ttft=` / 否则 `client_ttft_ms` | 首 token；热 session 会明显低于冷启动 |
| **client_ttft_ms** | HTTP 首 content chunk | 含代理开销，仅作参考 |
| **curl_wall_ms** | 整次 HTTP | 端到端，不是 decode 专用 |

若 `completion_tokens=0` 或 `tok_per_s=n/a`：**本次无效**，先看 `serve.log`，不要写进报告。

---

## 环境准备（一次性）

```bash
cd /app/flashcli

# FlashRT 臂
# - bundle 已 build：bundles/qwen_nvfp4/build.sh
# - 权重：~/.flashcli/models/qwen36-27b-nvfp4/checkpoint + mtp_fp8

# 基线臂默认与 FlashRT 同目录（pull 一次即可）：
#   ~/.flashcli/models/qwen36-27b-nvfp4/checkpoint

# 仅当要做 FP8 对照时再拉：
# huggingface-cli download Qwen/Qwen3.6-27B-FP8 \
#   --local-dir ~/.flashcli/models/qwen36-27b-fp8/checkpoint

# 基线服务（推荐）
pip install -U vllm   # 需支持 Qwen3.6 的版本（你环境 vllm 0.22.0 OK）

# vLLM 启动前（48GB）：
pip uninstall -y flash-attn
pip install 'kernels>=0.12,<0.13'   # 勿 pip install -U kernels（0.15+ 与 transformers 5.9 崩）
# --quick 默认 VLLM_MAX_MODEL_LEN=8192；首次 /health 可能需 5–10 分钟
```

长测可比 env（FlashRT 臂，与 codeplan 一致）：

```bash
export FLASHRT_QWEN36_LONG_KV_CACHE=fp8
export FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=512
```

---

## 测试流程（按顺序，不要跳）

### 步骤 0：同步脚本

容器内 `/app/flashcli` 与仓库一致后再跑。

### 步骤 1：冒烟 — FlashRT 单臂（~2 分钟）

```bash
bash scripts/bench_qwen36_compare.sh --quick --flashcli-only
```

**通过标准**：`flashcli/qwen36_short.metrics.jsonl` 里 scored 轮 `completion_tokens≈64`，`REPORT.md` 里 decode tok/s 有数值（非 n/a）。

### 步骤 2：冒烟 — vLLM 基线（~3–5 分钟，含首次加载）

```bash
bash scripts/bench_qwen36_compare.sh --quick --pytorch-only --vllm
# 默认：vllm serve ~/.flashcli/models/qwen36-27b-nvfp4/checkpoint
```

**通过标准**：`completion_tokens≈64`；正文应是量子纠缠段落，**不要**出现 `Here's a thinking process`。vLLM 需 `chat_template_kwargs.enable_thinking=false`（脚本已在 serve 与 payload 中配置）。

### 步骤 3：正式可比 — 短 + 长 256K（FlashRT，~30min+）

```bash
bash scripts/bench_qwen36_compare.sh --comparable --flashcli-only
```

对齐 `codeplan/bench_report_qwen_nvfp4.md`：12 轮、丢前 2、后 10 轮均值、`warmup-preset auto`。

### 步骤 4：正式可比 — 双臂（FlashRT + vLLM，串行占 GPU）

```bash
bash scripts/bench_qwen36_compare.sh --comparable --vllm --short-only
# 48GB 上 vLLM 长上下文 256K 仍不现实；短测双臂用同一 NVFP4 权重
```

输出：`/tmp/qwen36-bench-*/REPORT.md`（含 Comparison 表）。

---

## compare.sh 常用参数

| 参数 | 含义 |
|------|------|
| `--quick` | 仅短上下文；3 轮；`max_seq=32768`；warmup none |
| `--comparable` | 短+长；12 轮 skip 2；`max_seq=262208`；warmup auto |
| `--flashcli-only` | 只跑 FlashRT |
| `--pytorch-only` | 只跑基线 |
| `--vllm` | 基线用 `vllm serve`（**推荐**） |
| `--hf-server` | 基线用自建 transformers（不推荐） |
| `--hf-checkpoint PATH` | 基线权重（默认 = FlashRT 的 `--checkpoint`，NVFP4） |
| `--report-only` | 仅从已有 workdir 生成报告 |

---

## 故障速查

| 现象 | 处理 |
|------|------|
| vLLM + NVFP4 被 compare 误杀 | 已修复：`wait_health` 用 backend `vllm`，不再因 `linear_attn MISSING` 拒绝 NVFP4 |
| vLLM NVFP4 起不来 | 看 `serve.log`；需 vLLM 支持 Qwen3.6 + compressed-tensors NVFP4（Blackwell）；失败再试 FP8 `--hf-checkpoint` |
| `server_ttft=n/a`, wall≈50ms, tok=n/a | 模型未生成；换 `--vllm` 或装 `flash-linear-attention causal-conv1d` |
| FlashRT decode ~60 vs codeplan ~84 | 确认 `src=serve_log`、warmup `auto`、同 `K=6`；勿用 wall−client 估算当引擎 decode |
| vLLM `flash_attn_2_cuda` undefined symbol | **`pip uninstall -y flash-attn`** 后重跑（TORCH_SDPA 仍会 import 坏包） |
| vLLM CUDA OOM @ max-model-len 32768 | 用默认 `VLLM_MAX_MODEL_LEN=8192`（--quick）或 `16384`；48GB 跑不了 27B@32K vLLM |
| vLLM `revision or a version must be specified` | `pip install 'kernels>=0.12,<0.13'`（不要用 `-U kernels`） |
| vLLM `finegrained-fp8` / `kernels` missing | 同上 |
| vLLM 长上下文 256K 基线 | **不支持**（48GB）；长测只比 FlashRT 臂 |
| vLLM 其它启动失败 | `vllm --version`；首次启动等 /health，看 serve.log |
| Bundle invalid | `bundles/qwen_nvfp4/build.sh` + `flashcli bundle validate` |

---

## 修订原则（后续只改一处）

1. **编排只改** `bench_qwen36_compare.sh`  
2. **HTTP 压测只改** `bench_qwen_curl.sh` / `bench_qwen_curl_stream.py`  
3. **基线优先 vLLM**；`bench_qwen36_hf_server.py` 仅作兜底  
4. 每次改完只更新本文「测试流程」四步，不增加新入口脚本  
