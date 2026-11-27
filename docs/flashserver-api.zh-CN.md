# flashserver：HTTP API

<p align="right"><a href="flashserver-api.md">English</a> · <strong>简体中文</strong></p>

守护进程在本机 `127.0.0.1:8790` 提供 HTTP API（Windows 安装器可能选择其他端口，
见 `%LOCALAPPDATA%\flashcli-desktop\api-url.txt`）。同一端口提供两个命名空间：

- `/v1/*` — **OpenAI 兼容网关**。应用和桌面只通过它做推理，不能启动/停止/加载/
  卸载模型，也拿不到 child serve endpoint。
- `/api/v1/*` — **管理 API**：缓存模型、磁盘 preload/unload、任务、应用、遥测、日志
  和管理 WebSocket。

[openapi.yaml](../go/internal/server/openapi.yaml) 是**权威契约**，服务也在 `/openapi.yaml` 提供；HTML 参考页在
`/docs`。网关与调度行为以
[flashserver_gateway_scheduler_spec.zh-CN.md](flashserver_gateway_scheduler_spec.zh-CN.md)
为准。

默认关闭鉴权。配置 token 后，除 `/health`、`/`、`/docs`、`/ui/*`、`/openapi.yaml`
外的所有路径都需要 `Authorization: Bearer <token>` 或 `X-Flashcli-Token`。

## 网关（`/v1`）

| 端点 | 说明 |
|---|---|
| `GET /v1/models` | OpenAI list，只返回本地已准备（preloaded 或 resident）的 bundle ref |
| `POST /v1/chat/completions`、`/completions`、`/responses`、`/embeddings`、`/moderations` | 模型声明对应 capability 时才开放 |
| `POST /v1/audio/*`、`/images/*`、`/videos`、`/messages`、`/messages/count_tokens` | 按 capability 开放 |
| `WS /v1/realtime` | 按 capability 开放 |

- `model` 必须是**完整 bundle ref**（`flashcli-bundle/<name>:<version>`），
  不支持短名、alias 或 latest 解析。
- 调度器自动准备缺失资产、在内部启停 resident。模型准备/启动过程中网关返回
  `503` + `Retry-After`，不会无限阻塞首个请求。缺失模型会启动后台 preload 并返回
  `503 model_preparing` + `X-Flashcli-Preload-Job`；正在启动的 resident 返回
  `503 model_starting` 与 `Retry-After: 2`。
- `503 no_placement` 和 `429 queue_full` 表示调度失败；响应中的 `model` 会重写为
  请求的完整 ref，child serve endpoint 绝不暴露。
- multipart 路由（`audio/transcriptions`、`audio/translations`、`images/edits`、
  `images/variations`、JSON 或 multipart 的 `videos`）从表单读取 `model`，上传体按
  `max_upload_bytes`（默认 256 MiB）限制并缓冲。
- `WS /v1/realtime` 通过 query 参数传 `model`，只有校验、preload、准入都成功后才升级。
  Anthropic `messages`/`count_tokens` 使用相同的 ref 与 capability 规则。
- 模型未声明对应能力时返回明确错误，不会静默转发。

## 管理（`/api/v1`）

| 分组 | 端点 | 说明 |
|---|---|---|
| 健康 / 版本 | `GET /health`、`GET /api/v1/version` | `/health` 不需要鉴权 |
| 模型 | `GET /api/v1/models`、`POST /api/v1/models/preload`、`POST /api/v1/models/unload`、`POST /api/v1/models/clean` | schema 见 [openapi.yaml](../go/internal/server/openapi.yaml) |
| 模型参数 | `GET/PUT/DELETE /api/v1/models/options` | `serve_options` + 已保存的 host/port，见 [flashserver-desktop.zh-CN.md](flashserver-desktop.zh-CN.md#启动参数与局域网访问) |
| 任务 | `GET /api/v1/jobs/{id}`、`GET /api/v1/jobs/{id}/events`、`POST /api/v1/jobs/{id}/cancel` | preload、install/prepare/setup 的异步任务句柄，进度也通过 `/api/v1/ws` 推送 |
| 系统 | `GET /api/v1/system`、`GET /api/v1/gpu`、`GET /api/v1/gpu/history`、`GET /api/v1/resources`、`GET /api/v1/devices`、`GET /api/v1/scheduler`、`GET /api/v1/storage` | 遥测、设备盘点与 placement 结果 |
| 日志 | `GET /api/v1/logs`、`GET /api/v1/logs/download` | `?kind=server\|model&ref=…&lines=N` |
| 目录 | `GET /api/v1/catalog`、`GET /api/v1/catalog/tags`、`GET /api/v1/catalog/{id}` | FlashHub 代理 |
| 设置 | `GET /api/v1/settings`、`PATCH /api/v1/settings` | 类型化全局设置；`writable` 列出可写字段（`mirror.enabled`） |
| 应用 | `GET/POST/DELETE /api/v1/apps/*`、`POST /api/v1/apps/{org}/{name}/setup` | 安装/准备/配置应用；推理一律走 `/v1` |
| 实时 / 界面 | `GET /api/v1/ws`、`GET /`、`GET /docs`、`GET /openapi.yaml` | WebSocket 状态与内置控制台 |

`GET /api/v1/models` 的模型对象包含 `capabilities` 数组。`null` 表示 host 不拥有该
serve 条目的路由（script/native 或未知）；`[]` 表示显式关闭 host 推理路由。响应中的
`loaded` 字段列出 resident 实例。

`GET /api/v1/settings` 是唯一的类型化全局设置文档。`mirror`、`scheduler`、`server`、
`paths` 均为生效值；只有 `writable` 列出的字段可用 `PATCH` 修改（当前为
`mirror.enabled`）。调度器和服务器字段为只读，需要修改 daemon 配置并重启。每模型的
host/port/serve options 仍放在 `/models/options`。

## 设备与 placement

- `GET /api/v1/devices` 返回 WSL 可见设备：NVIDIA dGPU（`nvidia-smi`）、CPU、内存和
  cgroup 限制。iGPU/AMD/Windows native 不在范围内。
- `GET /api/v1/scheduler` 返回 resident 模型、槽位、队列/预留，以及每个已缓存 serve
  bundle 的 `ResourceRequirement`：匹配的 GPU runtime cell、满足 `gpu_count` 与 VRAM 需求
  （`min_vram_mib + vram_headroom_mib`，或 legacy 6144 MiB 下限）的设备、是否存在 CPU
  runtime，以及无 placement 的原因（`no_compatible_runtime` / `resource_exhausted`）。
- placement 只由 host 决定。bundle 只声明 `min_vram_mib`、可选 `gpu_count` 和可选
  `min_ram_mib`，绝不选择设备。
- 只有在不存在兼容 GPU runtime 时 CPU 才是候选；显存暂时不足不会触发 CPU 回退。

## 缓存模型生命周期

- `POST /api/v1/models/preload` 下载 bundle 和权重、准备运行时/venv，不启动 serve。
  幂等；运行中返回 job。`force=true` 会重新下载已缓存的 bundle/权重（桌面
  **重新同步** 修复动作），模型 resident 时返回 409。
- `POST /api/v1/models/unload` 停止 resident 并删除 bundle、权重、运行时和缓存记录。
  resident 或有 active 请求时返回 `409 model_busy`；`wait_seconds` 等待，`force`
  先停止。仍被其他 ref 引用的共享 bundle/权重/运行时保留。
- `POST /api/v1/models/clean` 是多 ref 清理版本；resident 模型会被跳过。

网关契约在此基础上增加由调度器管理的 resident 启停；见
[flashserver_gateway_scheduler_spec.zh-CN.md](flashserver_gateway_scheduler_spec.zh-CN.md)。

## 示例

```bash
# 预加载磁盘资产，不启动模型
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/api/v1/models/preload

# 读取设置 / 切换国内镜像（当前唯一可写字段）
curl http://127.0.0.1:8790/api/v1/settings
curl -X PATCH -H 'Content-Type: application/json' \
  -d '{"mirror":{"enabled":true}}' \
  http://127.0.0.1:8790/api/v1/settings

# 通过网关推理（调度器自动启动 resident）
curl -H 'Content-Type: application/json' \
  -d '{"model":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0",
       "messages":[{"role":"user","content":"Hello"}]}' \
  http://127.0.0.1:8790/v1/chat/completions
```

- 当 `addr` 绑定 `0.0.0.0` 且没有配置 token 时，局域网内其他设备可直接访问 API。

## 清理语义

- **共享缓存**（`~/.flashcli/cache`、`python`、`tools`）——
  `POST /api/v1/storage/clean {"targets":["cache"]}`（CLI：`flashcli cache clean`）。
- **模型数据**（Bundle、每个 bundle 的运行时、权重）——
  `POST /api/v1/models/clean {"refs":[...]}`（CLI：`flashcli bundle clean`）。仍被其他缓存
  ref 引用的共享权重/运行时保留；两个接口都返回释放字节数。

磁盘统计和清理路径来自共享的 `host` 层，因此 CLI 与 API 始终一致。幂等性、错误码和
请求/响应结构以 [openapi.yaml](../go/internal/server/openapi.yaml) 为准。
