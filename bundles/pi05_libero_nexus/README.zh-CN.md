# pi05_libero_nexus

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**Pi0.5 LIBERO VLA —— 基于 [FlashRT-Nexus](https://github.com/LiangSu8899/FlashRT-Nexus) 的有状态服务。**

| | |
|---|---|
| **FlashHub ref** | `flashcli-bundle/pi05_libero_nexus:1.0.0` |
| **权重** | [`lerobot/pi05_libero_finetuned_v044`](https://huggingface.co/lerobot/pi05_libero_finetuned_v044)（约 7 GB，自动下载）|
| **Substrate** | FlashRT `d0db114` + Nexus `8f13a3a`（复合标签 `frd0db114.nx8f13a3a`）|
| **Bundle 格式** | [flashcli-model-bundle v3](../../docs/bundle_publish_standard.zh-CN.md) |

本 bundle 在 Pi0.5 LIBERO 策略之上，叠加 FlashRT 推理引擎和 FlashRT-Nexus 服务底座。相比老的 `pi05_libero`（单次推理脚本），本 bundle 提供：

- 长驻 **HTTP serve** 模式，`/v1/chat/completions` 每次调用执行一次 `act()`
- **Episode 控制**：`POST /v1/session/snapshot`、`POST /v1/session/reset/{capsule}`，通过 Nexus capsule 实现热启动 / 撤销 / 回合重置
- 底座信息端点 `GET /v1/substrate`
- 标准的 **engine 模式 run**，用于单次推理和 benchmark

同一 bundle 同时支持 `flashcli run` 和 `flashcli serve`。

> **Prompt 处理**：Pi0.5 Nexus producer **在模型加载时把任务指令烧入**，不暴露动态 prompt port。指令固定为 manifest 的 `model.prompt`（可通过 `--warmup_prompt` serve 选项覆盖）。`/v1/chat/completions` 的 `content` 字段在推理时**被忽略** —— 只有 `extras.images` 真正进入策略。切换任务需要用不同的 `--warmup_prompt` 重启服务。

## 支持环境

| 字段 | 值 |
|---|---|
| Python ABI | `310`（CPython 3.10）|
| GPU | SM 120（Blackwell：RTX 50 系列）|
| CUDA | 13.0 |
| 系统 / 架构 | linux / x86_64 |
| Runtime cell | `sm120-cu130-linux-x86_64-py310` |

## 快速开始

```sh
# 1) 校验布局（离线、无需 GPU）
flashcli bundle validate bundles/pi05_libero_nexus

# 2) 拉权重 + PaliGemma tokenizer + 安装 Python 依赖到 bundle venv
flashcli pull bundles/pi05_libero_nexus

# 3) 单次推理
flashcli run bundles/pi05_libero_nexus \
    --prompt "pick up the red block and place it in the tray" \
    --image cam0.jpg,cam1.jpg

# 4) 长驻有状态服务
flashcli serve bundles/pi05_libero_nexus --port 8080 &

# 另一个终端：
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"pick up the red block"}],
         "extras":{"images":["<base64-jpeg>","<base64-jpeg>"]}}'

# Episode 控制：
curl -X POST 'http://127.0.0.1:8080/v1/session/snapshot?name=after_pickup'
curl -X POST http://127.0.0.1:8080/v1/session/reset/after_pickup
curl http://127.0.0.1:8080/v1/substrate
```

`flashcli pull` 完成后，所有推理路径**完全离线**——运行时不再下载、不再 pip 安装。

## 目录结构

```
bundles/pi05_libero_nexus/
├── flashcli-bundle.json               # manifest（entry.run + entry.serve + substrate 块）
├── flash_rt/                          # 精简版 FlashRT Python 包（仅 Pi0.5 子集）
├── runtime/
│   └── sm120-cu130-linux-x86_64-py310/
│       ├── flash_rt_kernels-d0db114-...-py310.so    # Python 扩展（顶层）
│       ├── flash_rt_fa2-d0db114-...-py310.so        # Python 扩展（顶层）
│       └── substrate/                                # 子目录：validator 跳过，loader 自取
│           ├── libflashrt_exec-d0db114-sm120-cu130-linux-x86_64.so
│           ├── libflashrt_cpp_pi05_c-d0db114-sm120-cu130-linux-x86_64.so
│           ├── libcapsule_nexus_flashrt-frd0db114.nx8f13a3a-sm120-cu130-linux-x86_64.so
│           ├── nexus_python/                         # vendor 的 Nexus serve 包
│           └── VERSION                               # ABI 指纹（单一真相）
├── run.py                             # RunEngine：单次推理
├── serve.py                           # ServeEngine：有状态 HTTP 服务
├── _substrate_loader.py               # 3 个 C 库的 ctypes 加载器 + ABI 校验
├── _pi05_infer.py / _pi05_compat.py   # Pi0.5 辅助函数（图像加载、FP8 shim）
├── build.sh / _bundle_build.sh        # 构建流水线
├── pack.sh / release.sh               # 打包 + FlashHub 发布
└── release-matrix.env                 # 发布矩阵定义
```

## 为什么是新 bundle？

`pi05_libero` 是 smoke test / benchmark 用的单次脚本。本 bundle 是**生产**形态：长驻、有状态、感知 episode，适合真实机器人控制循环。分开避免破坏现有 `pi05_libero` 用户。

## 底座 ABI 指纹

`runtime/<env_key>/substrate/VERSION` 记录本 bundle 编译时所用的精确 FlashRT + Nexus commit。加载期 fail-fast：如果 `libcapsule_nexus_flashrt.so` 未链接同目录的 `libflashrt_exec.so`（例如有人替换了其中一个），`_substrate_loader` 启动时立即报错。

## 构建 / 发布

维护者文档：[`BUILD.md`](BUILD.md) / [`BUILD.zh-CN.md`](BUILD.zh-CN.md)。

