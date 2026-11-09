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
- 不做 remote 模式；推理 endpoint 返回给客户端，本地控制台通过同源 `/v1/ui/chat` 代转以避免浏览器 CORS。
- 默认**关闭鉴权**（单用户本地守护进程）。需要时用 `--token` 或配置里的 `token` 开启，API 调用需带 `X-Flashcli-Token` 或 `Authorization: Bearer`。
- `flashserver` 必须开机启动并常驻。显存和槽位允许时可以加载多个模型。

## 本地控制台

安装后打开 `http://localhost:8790/`。内置控制台展示 GPU/显存、服务运行时长、缓存模型、已加载模型、日志，并支持加载/卸载模型和对话测试。页面随二进制内嵌，不需要额外资源或 Node 构建。

## Windows UI 安装包

Windows 用户应优先使用 UI 安装包，而不是命令行：

```text
FlashServer-Setup-<version>.exe
```

安装包会以管理员权限运行，检查/安装 WSL2 Ubuntu，安装 Linux payload，启动
`flashserver.service`，创建 Windows 登录任务，并检查守护进程。成功后自动打开
`http://localhost:8790/`（本地控制台）。如果启用 WSL2 需要重启，重启后再次运行
安装包即可；setup 引擎是幂等的。

自动化场景仍可使用 CLI：

```powershell
flashserver-setup.exe --backend wsl
```

## 安装

Linux：

```bash
sudo flashserver-setup
```

安装到 `/usr/local/bin`，写入 `/etc/flashserver/config.json`，创建 `flashserver.service`，设置开机启动，并检查 `/health`。

Windows：

```powershell
flashserver-setup.exe
```

使用官方 Ubuntu WSL2（不制作自定义镜像），在 `/etc/wsl.conf` 启用 systemd，在 WSL 内安装 Linux 二进制和 `flashserver.service`，并创建 `flashserver-wsl` 登录任务。

默认会下载匹配的 `flashcli-linux-<arch>` 和 `flashserver-linux-<arch>` release assets，并校验 `sha256sums.txt`。也可以用 `--bin-dir DIR` 使用本地资产，或用 `--release-version` / `--release-base` 固定 release 来源。

`--backend` 默认是 `auto`（Linux 为 `native`，Windows 为 `wsl`），通常不需要手动指定。`--dry-run` 只打印安装计划，不修改主机。`--no-service` 只安装二进制和配置，适用于容器或没有运行 systemd 的环境（之后手动运行 `flashserver --config ...`）。

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
GET  /v1/system                 OS/WSL/GPU/驱动/运行时长/版本
GET  /v1/logs                   ?kind=server|model&ref=...&lines=N
GET  /v1/gpu
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/models/load            {"ref":"...","async":true} → job_id（或 endpoint/pid/state）
POST /v1/models/unload          {"ref":"..."}
POST /v1/ui/chat                本地控制台代转：{"ref":"...","body":{...}}
GET  /                          内置本地控制台
```

不提供 `/v1/infer`。`load` 成功后直接访问返回的 `endpoint`。

```bash
curl -H "X-Flashcli-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

`load` 要求 bundle 提供 `serve` 入口。只有 `run` 的 bundle（VLA 策略等）会被立即拒绝，并返回 bundle 自身的原因，例如 `bundle "pi05_libero" does not support serve`；这类模型请使用 `flashcli run <ref>`。

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

Linux 使用 system-level systemd service。WSL 启用 systemd，并用 Windows `ONLOGON` 任务启动 WSL 发行版，同时以隐藏的 `sleep infinity` 会话保持其常驻；否则 WSL 的 `vmIdleTimeout` 会在最后一个会话退出约一分钟后停掉发行版（以及常驻服务）。本阶段不制作自定义 WSL 镜像。

## 卸载

```bash
sudo flashserver-setup --uninstall
```

移除 service、配置和 flashserver 二进制，保留 `FLASHCLI_HOME`、bundle 和模型权重。Windows 通过 UI 安装包卸载；WSL 发行版和模型缓存保留。
