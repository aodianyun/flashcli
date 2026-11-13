# flashserver：HTTP API

<p align="right"><a href="flashserver-api.md">English</a> · <strong>简体中文</strong></p>

守护进程在本机 `127.0.0.1:8790` 提供 HTTP API（Windows 安装器可能选择其他端口，
见 `%LOCALAPPDATA%\FlashServer\api-url.txt`）。[openapi.yaml](openapi.yaml) 是
**权威契约**，服务也在 `/openapi.yaml` 提供；HTML 参考页在 `/docs`。

默认关闭鉴权。配置 token 后，除 `/health`、`/`、`/docs`、`/ui/*`、`/openapi.yaml`
外的所有路径都需要 `Authorization: Bearer <token>` 或 `X-Flashcli-Token`。

## 端点目录

| 分组 | 端点 | 说明 |
|---|---|---|
| 健康 / 版本 | `GET /health`、`GET /v1/version` | `/health` 不需要鉴权 |
| 模型 | `GET /v1/models`、`GET /v1/models/loaded`、`POST /v1/models/load`、`POST /v1/models/unload`、`POST /v1/models/smoke`、`POST /v1/models/clean` | schema 见 [openapi.yaml](openapi.yaml) |
| 模型参数 | `GET/PUT/DELETE /v1/models/options` | `serve_options` + 已保存的 host/port，见 [flashserver-desktop.zh-CN.md](flashserver-desktop.zh-CN.md#启动参数与局域网访问) |
| 任务 | `POST /v1/pull`、`GET /v1/jobs/{id}`、`GET /v1/jobs/{id}/events`、`POST /v1/jobs/{id}/cancel` | 异步任务，进度也通过 `/v1/ws` 推送 |
| 系统 | `GET /v1/system`、`GET /v1/gpu`、`GET /v1/gpu/history`、`GET /v1/resources`、`GET /v1/storage` | 遥测与容量 |
| 日志 | `GET /v1/logs`、`GET /v1/logs/download` | `?kind=server\|model&ref=…&lines=N` |
| 目录 | `GET /v1/catalog`、`GET /v1/catalog/tags`、`GET /v1/catalog/{id}` | FlashHub 代理 |
| 镜像 | `GET /v1/mirror`、`POST /v1/mirror` | 对新下载启用/关闭国内镜像 |
| 实时 / 界面 | `GET /v1/ws`、`GET /`、`GET /docs`、`GET /openapi.yaml`、`POST /v1/ui/chat` | WebSocket 状态与内置控制台 |

## 示例

```bash
# 加载模型，然后请求返回的 endpoint
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

- `load` 要求 bundle 提供 `serve` 入口：只有 `run` 的 bundle 会被拒绝
  （`bundle "..." is run-only (no serve entry)`），请改用 `flashcli run`。
- 没有 `/v1/infer`，加载后直接访问返回的 `endpoint`。
- `POST /v1/models/smoke` 对 run-only bundle 以低优先级执行 `flashcli run`，或对已启动的
  serve 模型发送一次 `ping` 对话请求；进度通过 `/v1/ws` 推送并追加到
  `<ref>.smoke.log`。
- 当 `addr` 绑定 `0.0.0.0` 且没有配置 token 时，局域网内其他设备可直接访问 API。

## 清理语义

- **共享缓存**（`~/.flashcli/cache`、`python`、`tools`）——
  `POST /v1/storage/clean {"targets":["cache"]}`（CLI：`flashcli cache clean`）。
- **模型数据**（Bundle、每个 bundle 的运行时、权重）——
  `POST /v1/models/clean {"refs":[...]}`（CLI：`flashcli bundle clean`）。仍被其他缓存
  ref 引用的共享权重/运行时保留；两个接口都返回释放字节数。

磁盘统计和清理路径来自共享的 `host` 层，因此 CLI 与 API 始终一致。幂等性、错误码和
请求/响应结构以 [openapi.yaml](openapi.yaml) 为准。
