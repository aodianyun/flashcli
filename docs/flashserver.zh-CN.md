# flashserver

<p align="right"><a href="flashserver.md">English</a> · <strong>简体中文</strong></p>

`flashserver` 是单机常驻的本地模型调度器：负责模型生命周期（准备、加载、启动、停止）
和 GPU 准入；真正的推理仍由 `flashcli serve` 子进程完成。

```text
flashserver-setup  安装二进制和开机服务（systemd / WSL2）
flashserver        常驻调度器 + 本地控制台 API（默认 127.0.0.1:8790）
flashcli serve     单模型进程，OpenAI 兼容 API
```

支持 Linux（systemd）和 Windows（WSL2，官方 Ubuntu rootfs）。不提供 remote 模式。
默认**关闭鉴权**（单用户本地守护进程）；用 `--token` 或配置里的 `token` 开启。

## 安装

### Windows 安装包

推荐使用 `flashserver-setup-windows-amd64-v<version>.exe`（管理员）。它以实时进度页
驱动 `flashserver-setup`，完成后打开桌面客户端：

```text
[1/8] 检查/启用 WSL2 → [2/8] 注册发行版 → [3/8] 启用 systemd
[4/8] 安装 Linux payload → [5/8] 写配置 + 服务 → [6/8] 启动服务
[7/8] 登录任务 + 防火墙规则 → [8/8] 等待 /health
```

- 需要重启 Windows 时退出码为 **3**，重启后再运行一次即可。重复运行是幂等的，
  用于修复安装，不会重复创建服务。
- 若 `8790` 被 Windows 保留（Hyper-V/WinNAT），setup 会自动选下一个空闲端口并写入
  `%LOCALAPPDATA%\FlashServer\api-url.txt`，客户端、安装器和 API 文档都读取该文件。
- 新安装导入 `flashserver_ubuntu`；已有 `/etc/flashserver/config.json` 的旧 `Ubuntu`
  会被复用。实际名称写入 `%LOCALAPPDATA%\FlashServer\distro.txt`。
- 新安装默认启用国内镜像，并添加 `FlashServer models` 防火墙规则
  （Private/Domain，默认放行所有 TCP 端口）。
- 失败对话框只显示 ASCII 日志片段；完整日志在
  `%LOCALAPPDATA%\FlashServer\logs\setup.log`。

### Linux

```bash
sudo flashserver-setup
```

安装 `/usr/local/bin/{flashcli,flashserver}`，写 `/etc/flashserver/config.json` 和
`flashserver.service`，设置开机启动并检查 `/health`。

### 命令行参数

| 参数 | 说明 |
|---|---|
| `--backend auto\|native\|wsl` | 默认 `auto`（Linux 用 native，Windows 用 WSL） |
| `--bin-dir DIR` | 使用本地 `flashcli-*` / `flashserver-*` 资产，不联网下载 |
| `--wsl-dir DIR` | 把 WSL 发行版迁移到其他 NTFS 盘 |
| `--distro-rootfs FILE` | 导入本地 rootfs 压缩包（离线安装） |
| `--progress-file FILE` | 机器可读的 `[n/8]` 行 + `DONE <code>`（0 就绪、3 需重启、2 出错） |
| `--no-service` | 只装二进制和配置（容器或无 systemd 环境） |
| `--dry-run` | 只打印计划，不修改主机 |
| `--uninstall` / `--purge-*` | 见 [服务生命周期](#服务生命周期) |

### 验证

```bash
curl -s http://127.0.0.1:8790/health
```

Windows 上端口可能不同，读 `%LOCALAPPDATA%\FlashServer\api-url.txt`。
干净虚拟机的安装验收步骤见 [installer/windows/README.md](../installer/windows/README.md)。

## 桌面客户端

Windows 安装包内置 `FlashServer.exe`（Rust + egui/eframe，不用 WebView，无控制台窗口）。
实时状态走 `/v1/ws`，命令走 HTTP。

- **概览**：GPU/显存/CPU/内存卡片与 5 分钟曲线、服务与磁盘卡片。
- **模型**：本地缓存 + FlashHub 搜索；分开展示 Bundle / 运行时 / 权重大小；
  **加载**准备模型，**启动**运行 serve 进程（**停止**结束它）；run/serve 冒烟测试
  带实时日志；支持多选清理。
- **日志**：服务日志或单个模型的 serve 日志，可清空和另存为。
- **设置**：服务启停、开机启动、国内镜像、共享缓存清理、WSL 资源与防火墙端口、
  主题（`Ctrl+T`）、API 文档。

服务状态与开机启动相互独立：停止不会关闭开机启动，开自启也不会启停服务。破坏性操作
都会二次确认，耗时操作显示进度遮罩。设置保存在
`%LOCALAPPDATA%\FlashServer\settings.json`。

## HTTP API

### 端点

```text
GET  /health
GET  /v1/version
GET  /v1/models                  缓存模型 + 已加载实例 + serve 能力
GET  /v1/models/loaded
GET  /v1/storage                 各区域唯一分配字节（硬链接只计一次）
GET  /v1/mirror                  国内镜像状态
POST /v1/mirror                  对新下载启用/关闭镜像
GET  /v1/resources               GPU、已加载模型、槽位
GET  /v1/system                  OS/WSL/GPU/驱动/CUDA/SM/torch/CPU/内存/运行时长
GET  /v1/logs                    ?kind=server|model&ref=...&lines=N&since=unix
GET  /v1/logs/download           完整服务/模型日志附件
GET  /v1/gpu                     设备 + CUDA 进程
GET  /v1/gpu/history             ?seconds=N 最近 GPU+CPU 遥测采样
GET  /v1/ws                      WebSocket：状态快照 + 任务进度
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/jobs/{id}/cancel        取消任务（smoke/下载/加载）
POST /v1/models/load             {"ref":"...","async":true} → job_id（或 endpoint/pid/state）
POST /v1/models/unload           {"ref":"..."}
GET  /v1/models/options          ?ref=... manifest serve_options + 已保存值
PUT  /v1/models/options          {"ref":"...","host":"0.0.0.0","port":0,"options":{...}}
DELETE /v1/models/options        ?ref=... 恢复默认值
POST /v1/models/smoke            {"ref":"..."} run-only 冒烟测试或已启动 serve 请求测试
POST /v1/models/clean            {"refs":[...]} 清理本地 Bundle/权重
POST /v1/storage/clean           {"targets":["cache"]} 只清理共享缓存
GET  /v1/catalog                 ?q=&tag=&sort=updated|downloads&page=&page_size=
GET  /v1/catalog/tags
GET  /v1/catalog/{id}            仓库详情 + 版本列表
POST /v1/ui/chat                 本地控制台代转：{"ref":"...","body":{...}}
GET  /docs                       HTML API 参考
GET  /openapi.yaml               OpenAPI 3.1 契约
GET  /                           内置本地控制台
```

### 示例

```bash
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

只有配置了 token 才需要加 `-H "X-Flashcli-Token: $TOKEN"`。`load` 要求 bundle 提供
`serve` 入口：只有 `run` 的 bundle 会被拒绝（`bundle "..." is run-only (no serve entry)`），
请改用 `flashcli run`。没有 `/v1/infer`，加载后直接访问返回的 `endpoint`。

`POST /v1/models/smoke` 对 run-only bundle 以低优先级执行 `flashcli run`，或对已启动的
serve 模型发送一次 `ping` 对话请求；进度通过 `/v1/ws` 推送并追加到 `<ref>.smoke.log`。

### 清理

- **共享缓存**（`~/.flashcli/cache`、`python`、`tools`）：`flashcli cache clean` 或
  `POST /v1/storage/clean {"targets":["cache"]}`。
- **模型数据**（Bundle、每个 bundle 的运行时、权重）：`flashcli bundle clean …` 或
  `POST /v1/models/clean {"refs":[...]}`。仍被其他缓存 ref 引用的共享权重/运行时保留；
  两个接口都返回释放字节数。

权威 schema 见 [openapi.yaml](openapi.yaml)，服务也在 `/openapi.yaml` 提供。

## 启动参数与局域网访问

每个模型的启动参数来自 bundle 的 `serve_options`（`flashcli-bundle.json`，含 v4 环境
overlay），再加上监听地址和端口：

- `host`：`0.0.0.0` 监听所有网卡，`127.0.0.1` 仅本机。
- `port`：`0` 用任意空闲端口；固定端口会先检查占用。
- 参数留空表示用 bundle 默认值；非空值以 `--flag value` 追加到 `flashcli serve`。
  `serve_options` 里的 host/ip/port 由上面的字段表示，不会重复追加。
- 保存在 `$FLASHCLI_HOME/flashserver/serve-options.json`（CLI、API、桌面共用）；
  模型运行中保存，需要停止再启动才生效。

Windows 的 localhost 转发让 `host=0.0.0.0` 在 Windows 上可通过
`http://localhost:<port>` 访问。局域网/公网访问需要镜像网络：

1. 设置 → WSL 资源 → 局域网访问 会向 `%USERPROFILE%\.wslconfig` 写入
   `networkingMode=mirrored`。
2. 客户端请求 UAC，按设置放行 Private/Domain 的 TCP 入站端口（留空 = 所有 TCP，
   例如 `18000-18999`）。
3. 应用设置会重启 WSL 和 `flashserver`，正在运行的模型会中断。

同一面板可修改 `.wslconfig` 的 `memory`/`processors`/`swap`（留空用 WSL 默认值：
内存 50%、全部逻辑 CPU、Swap 25%），对所有 WSL2 发行版生效。镜像网络需要
Windows 11 22H2+。公网访问还需要额外的 Public 规则和路由器端口映射；不要在没有
token 的情况下直接暴露 API。

## 配置

```json
{
  "addr": "127.0.0.1:8790",
  "flashcli_bin": "/usr/local/bin/flashcli",
  "public_host": "127.0.0.1",
  "serve_host": "127.0.0.1",
  "log_dir": "/home/me/.flashcli/logs/serve",
  "max_loaded": 0,
  "min_free_vram_mib": 2048
}
```

- `max_loaded=0` 只按显存准入。bundle 声明的 `resources.min_vram_mib` 必须能放进
  「空闲显存 − `min_free_vram_mib`」，否则 `load` 返回 `409 RESOURCE_EXHAUSTED`；
  槽位上限也把正在启动的模型计入。
- WSL 默认：`addr=0.0.0.0:8790`、`public_host=localhost`、`serve_host=0.0.0.0`
  （Windows 通过 localhost 转发访问服务）。
- `token` 可选。设置后除 `/health`、`/`、`/docs`、`/ui/*`、`/openapi.yaml` 外的所有
  路径都需要 `Authorization: Bearer <token>` 或 `X-Flashcli-Token`。
- 镜像：设置 → 下载源 或 `POST /v1/mirror {"enabled":true}` 会写
  `~/.flashcli/mirror.env`（阿里云 pip、hf-mirror、gh-proxy、Gitee、SJTU torch），
  对新下载立即生效，不需要重启服务。

## 服务生命周期

`load` 时 `flashserver` 启动
`flashcli serve <ref> --host <serve_host> --port <allocated>`，等 `/health` 通过后才
报告 `ready`；`unload`/退出会停止该子进程。Linux 使用 systemd 单元。WSL 使用 systemd
加 `flashserver-wsl` 登录任务：任务启动发行版并用隐藏的 `sleep infinity` 会话保持常驻
（否则 WSL 在空闲约一分钟后会停掉发行版）。

```powershell
flashserver-setup.exe --stop-service        # 停止服务并关闭开机启动
flashserver-setup.exe --disable-autostart   # 保持运行，仅关闭开机启动
flashserver-setup.exe --enable-autostart    # 仅开启开机启动，保持当前状态
flashserver-setup.exe --start-service       # 开启开机启动并启动服务
```

```bash
sudo flashserver-setup --uninstall          # 保留模型缓存和发行版
```

| 卸载参数 | 删除内容 |
|---|---|
| `--purge-models` | `FLASHCLI_HOME`（bundle、权重、运行时、缓存）以及解压出的 `flashcli-bundle` |
| `--remove-cli` | `/usr/local/bin/flashcli` |
| `--purge-settings` | 桌面设置和安装日志（`%LOCALAPPDATA%\FlashServer`） |
| `--purge-distro` | 当前 WSL 发行版及其 `ext4.vhdx`（内部数据全部丢失；仅 WSL） |

Windows 卸载器提供同样的四项清理和全选；静默卸载保留全部数据。卸载时若模型正在
加载或启动，会先停止服务和相关任务（缓存状态会在下次安装后继续）。

## 注意事项与排障

- **磁盘位置**：权重和运行时在 WSL 的 `ext4.vhdx` 里，默认与安装目录同级
  （安装在 `Program Files` 下时为 `%LOCALAPPDATA%\FlashServerWSL`）。删除数据不会
  自动缩小：先用 `flashcli du` / `flashcli cache clean` / `flashcli bundle clean`
  清理，再用 `wsl --manage <distro> --set-sparse true` 或 `diskpart` 压缩。
- **受限网络**：`wsl --install` 无法访问 Store/GitHub（或 90 秒无进度）时，setup 从
  清华/中科大镜像（其次 `cloud-images.ubuntu.com`）导入官方 Ubuntu 24.04 rootfs；
  离线安装可用 `--distro-rootfs FILE`。
- **在 WSL 内检查**：
  ```bash
  wsl -d flashserver_ubuntu
  ps -ef | grep '[f]lashcli.*serve'
  cat /proc/<pid>/cmdline | tr '\0' ' '; echo   # 参数以 NUL 分隔
  cat /root/.flashcli/flashserver/serve-options.json
  journalctl -u flashserver -n 100 --no-pager
  ```
  服务以 root 运行（除非用了 `--home`，`FLASHCLI_HOME=/root/.flashcli`）；实际发行版
  名称见 `%LOCALAPPDATA%\FlashServer\distro.txt`。
- **耗时参考**（RTX 4060 8 GB、约 100 Mbit/s）：安装器已缓存 4–6 秒（缺少 WSL2 时
  5–15 分钟并通常需重启一次）；Bundle 同步约 46 秒 / 181 MiB；权重约 6–7 分钟 /
  ~7 GiB；Python + torch 2–5 分钟；模型加载约 40 秒。已缓存时安装 + 加载约 8 秒。
