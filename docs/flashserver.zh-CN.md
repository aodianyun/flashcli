# flashserver

<p align="right"><a href="flashserver.md">English</a> · <strong>简体中文</strong></p>

`flashserver` 是个人 PC 上常驻的本地模型调度器。它负责模型生命周期和资源准入；实际推理仍然由 `flashcli serve` 子进程完成。

```text
flashserver-setup  → 安装二进制和常驻服务
flashserver        → 常驻调度器 + HTTP API
flashcli serve     → 单模型进程，OpenAI-compatible API
```

## 范围

- 支持 Linux 原生和 Windows WSL2（官方 Ubuntu 发行版）。
- 不做 remote 模式，不代理推理；`flashserver` 返回每个模型的 endpoint。
- `flashserver` 必须开机启动并常驻。显存和槽位允许时可以加载多个模型。

## 安装

Linux：

```bash
sudo flashserver-setup --backend native --bin-dir /path/to/release-assets
```

安装到 `/usr/local/bin`，写入 `/etc/flashserver/config.json`，创建 `flashserver.service`，设置开机启动，并检查 `/health`。

Windows：

```powershell
flashserver-setup.exe --backend wsl --bin-dir C:\path\to\release-assets
```

使用官方 Ubuntu WSL2（不制作自定义镜像），在 `/etc/wsl.conf` 启用 systemd，在 WSL 内安装 Linux 二进制和 `flashserver.service`，并创建 `flashserver-wsl` Windows 启动任务。`--bin-dir` 中需要 `flashcli-linux-<arch>` 和 `flashserver-linux-<arch>`。

`--dry-run` 只打印安装计划，不修改主机。`--no-service` 只安装二进制和配置，适用于容器或没有运行 systemd 的环境（之后手动运行 `flashserver --config ...`）。

## 配置

```json
{
  "addr": "127.0.0.1:8790",
  "token": "local-secret",
  "flashcli_bin": "/usr/local/bin/flashcli",
  "public_host": "127.0.0.1",
  "serve_host": "127.0.0.1",
  "log_dir": "/home/me/.flashcli/logs/serve",
  "max_loaded": 0,
  "min_free_vram_mib": 2048
}
```

- `max_loaded=0`：只按显存准入。
- WSL 使用 `addr=0.0.0.0:8790`、`public_host=localhost`、`serve_host=0.0.0.0`，通过 localhost forwarding 让 Windows 访问 WSL 服务。
- `token` 保护除 `/health` 外的 API；请求头使用 `Authorization: Bearer <token>` 或 `X-Flashcli-Token`。

## API

```text
GET  /health
GET  /v1/version
GET  /v1/models                 本地缓存模型 + 已加载实例
GET  /v1/models/loaded
GET  /v1/storage
GET  /v1/resources              GPU、已加载模型、槽位
GET  /v1/gpu
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/models/load            {"ref":"..."} → endpoint/pid/state
POST /v1/models/unload          {"ref":"..."}
```

不提供 `/v1/infer`。`load` 成功后直接访问返回的 `endpoint`。

```bash
curl -H "X-Flashcli-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

## 资源准入

以下情况 `load` 返回 `409 RESOURCE_EXHAUSTED`：

- `max_loaded > 0` 且已加载/正在加载数量达到上限；
- bundle 声明了 `resources.min_vram_mib`，且空闲显存减去 `min_free_vram_mib` 后不足。

bundle 应声明实测显存：

```json
"resources": {
  "min_vram_mib": 12288
}
```

v4 环境 overlay 可以覆盖。未声明该字段的 bundle 只按槽位限制准入。

## 服务生命周期

`flashserver` 在 `load` 时启动 `flashcli serve <ref> --host <serve_host> --port <allocated>`，在 `unload`/退出时停止子进程；等待 `/health` 后才返回 `ready`。

Linux 使用 system-level systemd service。WSL 启用 systemd，并用 Windows `ONSTART` 计划任务启动 WSL 和 service。本阶段不制作自定义 WSL 镜像。
