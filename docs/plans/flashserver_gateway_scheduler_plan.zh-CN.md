# flashserver 网关与调度开发计划

<p align="right"><a href="flashserver_gateway_scheduler_plan.md">English</a> · <strong>简体中文</strong></p>

契约见 [../flashserver_gateway_scheduler_spec.zh-CN.md](../flashserver_gateway_scheduler_spec.zh-CN.md)。本文是执行计划；
出现行为分歧时以规范为准。

## 1. 目标

从“load 返回 child endpoint”迁移到：

- 应用和桌面只调用 `/v1/*` OpenAI 网关；
- flashserver 负责 preload、placement、resident start/stop、lease、eviction、unload；
- 管理接口统一到 `/api/v1/*`；
- 应用不能启停/加载/卸载模型，也不能选择设备；
- preload/remove 是磁盘操作，resident start/stop 是内部调度。

不需要兼容旧版本；桌面是唯一客户端，同一次发布一起改。

## 2. 工作流

### M0 — 契约与路由拆分

交付：

- 本计划 + 权威规范（英文 + 中文镜像）并加入索引。
- `/v1/*` 只保留网关；所有管理路由迁到同一端口的 `/api/v1/*`。
- `/health`、`/`、`/ui/*`、`/docs`、`/openapi.yaml` 保持原位置。
- 桌面管理基址切换到 `/api/v1`；管理 WebSocket 到 `/api/v1/ws`。
- OpenAPI 按两个命名空间更新。
- AGENTS/CONTRIBUTING 引用本规范为强制要求。

退出条件：

- `/v1/*` 下不再有管理路由；
- 桌面能通过 `/api/v1` 获取模型/资源/日志；
- 现有非网关测试迁移到新路径；
- 文档链接和中文镜像检查通过。

### M1 — 磁盘状态、preload、unload

交付：

- 持久化每个 ref 的 preload 状态：`absent`、`preloading`、`preloaded`、`unloading`。
- `preload` job 封装 `host.Pull`，支持去重、进度、取消、续传。
- `unload` job 封装 `host.RemoveCachedRef`：
  - busy/lease 检查、`wait_seconds`、`force`；
  - 删除前先 stop resident；
  - 保留共享 bundle/weights/runtime；
  - 删除 preload 状态。
- `/api/v1/models/preload`、`/api/v1/models/unload`、`/api/v1/models` 状态。
- preload 不启动 serve，不占显存。

测试：

- preload 幂等、并发去重、失败后续传。
- unload busy：409、等待、超时、force。
- 共享资产保留，独占资产删除。
- daemon 重启后 preload 状态保留。

退出条件：

- 缺失模型可准备且无 child 进程；
- resident/busy 时普通 unload 不删资产；
- 状态跨重启保留。

### M2 — 设备盘点与资源账本

交付：

- WSL 设备：NVIDIA dGPU（`nvidia-smi`）、CPU、RAM、cgroup 限制。
- runtime cell 与设备兼容映射。
- VRAM/RAM/CPU 预留和 `vram_headroom_mib`。
- `/api/v1/devices`、`/api/v1/scheduler`。
- manifest 资源字段：`min_vram_mib`（GPU）、可选 `gpu_count`、可选 `min_ram_mib`（CPU）。
- 校验：GPU runtime 必须有 `min_vram_mib`；`gpu_count >= 1`；bundle 不允许
  placement/device 字段。

测试：

- 假多 GPU 盘点；单卡 free memory；`gpu_count` 全有或全无预留。
- CPU/RAM 账本和 WSL 内存上限。
- 无 runtime cell 返回 `no_compatible_runtime`。
- 非法资源字段使 `bundle validate` 失败。

退出条件：

- 不启动进程就能回答“该 ref 能否在本机运行、用哪些设备”；
- Go 中没有模型专属资源逻辑。

### M3 — 调度器 resident 生命周期

交付：

- `LoadScheduled(ref)` 与管理员 preload 分离；不持久化、不 pin。
- resident 状态：stopped/starting/ready/busy/stopping。
- lease 增减；有 lease 不 evict/unload。
- `max_loaded`、LRU 空闲 stop、`idle_stop_seconds`、`queue_*`。
- placement、eviction、显存释放等待、重试。
- 仅无兼容 GPU runtime 时才 CPU 回退。
- `/api/v1/models` resident 字段、`/api/v1/scheduler` 队列/预留。

测试：

- 两个请求共享一次加载；加载去重。
- LRU 只淘汰空闲，不淘汰 busy。
- max_loaded/VRAM 准入、headroom。
- 多 GPU 预留；CPU 回退规则。
- 队列超时 429、资源不足 503。
- 空闲 stop 保持 preloaded，下次请求再启动。
- 崩溃/OOM 只重载一次，不循环。

退出条件：

- 没有应用可见的 start/stop；
- resident 生命周期完全由 scheduler 管理；
- 准入/淘汰用假设备全面测试。

### M4 — 网关核心

交付：

- `/v1/models` 返回 preloaded/resident refs 的 OpenAI list。
- JSON 路由：chat、completions、responses、embeddings、moderations。
- 完整 ref 校验；capability gate。
- auto-pull：后台 job + `503 model_preparing` + `Retry-After` +
  `X-Flashcli-Preload-Job`。
- auto-resident：有界等待 + `503 model_starting` + `Retry-After: 2`。
- 反向代理：状态、头、body、客户端取消；不暴露 child endpoint。
- 响应 `model` 重写为请求的完整 ref（JSON 和 SSE）。
- OpenAI 风格错误：`model_not_found`、`model_preparing`、`model_starting`、
  `no_placement`、`resource_exhausted`、`queue_full`、`model_busy`。
- Retry-After 严格按规范。

测试：

- JSON 代理和错误透传/规范化。
- SSE flush、chunk 顺序、断开取消。
- auto-pull 503、重试、成功；job 去重。
- preloaded 但 stopped -> start；busy -> lease。
- 未知 ref 404；未声明 capability 4xx。
- 不泄漏 child endpoint。

退出条件：

- 标准 OpenAI 客户端可直接使用 `http://host:8790/v1`；
- 首个请求不会无限阻塞在 preload/start。

### M5 — multipart、WebSocket、完整协议

交付：

- audio/images/videos multipart 的 `model` 提取（有界缓冲、可取消）。
- WebSocket `/v1/realtime` 目标选择与代理。
- Anthropic messages/count_tokens 使用同一网关规则。
- capability 路由错误。
- 请求/响应大小限制、超时、流式背压。

测试：

- multipart 有/无 model；大 body；客户端取消。
- WebSocket 连接/升级/双向帧/关闭。
- 混合能力模型拒绝未声明路由。
- 慢消费者和上游失败。

退出条件：

- 所有声明的网关路由可用；
- host 中无模态专属逻辑，未来 schema 仍由 bundle 声明。

### M6 — 应用与桌面迁移

交付：

- app install/prepare 只 preload refs，不启停模型。
- 删除 app start/stop 接口和桌面控件。
- setup 脚本使用 `FLASHCLI_API_BASE=http://<host>:8790/v1`。
- AppState 不再把 child `pid`/`endpoint` 作为推理入口。
- 桌面管理 `/api/v1`，推理 `/v1`；显示 preload/resident/device 状态，只保留磁盘
  preload/unload 操作。
- 模型“使用”示例改为网关。

测试：

- app install/preload 后通过 `/v1` 推理，不使用 endpoint。
- 桌面 `/api/v1` 路由覆盖测试。
- 旧 start/stop 返回 404，桌面不再调用。
- setup 脚本环境指向网关。

退出条件：

- 应用/桌面无任何模型 start/stop 或 child endpoint 调用；
- 推理只走 `/v1`。

### M7 — 加固与发布

交付：

- 可观测性：请求日志、preload/resident/evict 事件、队列/lease 指标。
- 安全：token 共用、child 仅 loopback、转发前移除 token。
- 配置校验和默认值。
- WSL dGPU 单卡/多卡和 CPU runtime 验收。
- OpenAPI、英文/中文文档、发布说明。
- 失败注入：断网、磁盘满、GPU OOM、child 崩溃、daemon 重启。

退出条件：

- WSL 真实 NVIDIA GPU 上完整验收通过；
- prepared 模型跨 daemon 重启保留；
- 真实 busy stream 下 unload/force 行为验证；
- 文档和规范同步更新。

## 3. 测试矩阵

| 区域 | 单元 | 集成 | 验收 |
|---|---|---|---|
| 完整 ref / 路由 | 是 | 是 | 是 |
| preload/unload | 是 | 是 | 是 |
| active lease / force | 是 | 是 | 是 |
| auto-pull Retry-After | 是 | 是 | 是 |
| resident start / idle stop | 是 | 是 | 是 |
| LRU / max_loaded / VRAM | 是 | 是 | 是 |
| 多 GPU `gpu_count` | 是 | 假设备 | WSL 有卡时真实验收 |
| CPU 回退规则 | 是 | 假设备 | WSL 有 CPU runtime 时验收 |
| JSON / SSE / multipart / WS | 是 | 是 | 是 |
| 应用/桌面无 start/stop | 静态 | 是 | 是 |

## 4. 完成标准

- 应用和桌面只使用 `/api/v1` 管理、`/v1` 推理。
- 应用不能启停/加载/卸载模型或看到 child endpoint。
- preload 准备磁盘资产，unload 按 busy/force 语义删除；自动 eviction 只 stop resident。
- 首个推理请求自动 pull/preload，未完成时返回标准 `503` + `Retry-After`，后台继续。
- placement 只由 host 决定；bundle 只声明 runtime 和资源需求。
- CPU 只在没有兼容 GPU runtime 时回退。
- WSL 支持 NVIDIA dGPU 和 CPU runtime；iGPU/Windows native 不在范围。
- 测试和英文/中文文档在同一次变更中更新。

## 5. 强制遵守

- 规范是权威；行为变化必须先更新英文规范和中文镜像，代码不得偏离。
- 不得在 `go/` 中加入模型专属参数、形状、placement 提示或设备选择。
- 不得恢复应用可见的模型 start/stop 或 child endpoint。
- 管理 API 不得放回 `/v1/*`。
- 每个新路由/状态/配置必须有测试、OpenAPI 和文档。
- `bundle validate` 与调度准入对资源字段的规则必须一致。
