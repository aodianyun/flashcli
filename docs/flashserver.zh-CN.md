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

安装后打开 `http://localhost:8790/`（默认端口；Windows 安装器在 8790 被占用/保留时可能选择其他端口，见“Windows UI 安装包”）。内置控制台展示 GPU/显存、利用率、温度、频率、功耗（驱动提供时）、CUDA/SM/torch 环境、CUDA 进程显存（原生 Linux；WSL 通常不暴露进程列表）、CPU 型号/核心/负载/每核利用率、内存/Swap、GPU 与 CPU 5 分钟曲线、服务运行时长、缓存模型、已加载模型、日志，并支持加载/卸载模型和对话测试。页面随二进制内嵌，不需要额外资源或 Node 构建。HTTP 契约发布在 `/openapi.yaml`，HTML 参考页在 `/docs`，源文件见 [openapi.yaml](openapi.yaml)。实时客户端可用 `GET /v1/ws`（1Hz 系统快照 + 任务进度）。`GET /v1/catalog` 代理 FlashHub 公共目录（搜索、分类、版本），`GET /v1/logs/download` 返回完整服务日志。

## 桌面客户端

Windows 安装包内置 `FlashServer.exe`：Rust + egui/eframe 原生客户端（不使用 WebView，启动无黑色控制台窗口），包含概览（卡片布局的 GPU/CPU 环境信息与 0-100 曲线、两行紧凑的服务/磁盘卡片、底部 GPU/显存/CPU/内存扁平状态条）、模型（本地缓存 + 按需搜索的 FlashHub 目录/分类/版本、Bundle/运行时/权重分开显示大小、就绪与启动状态、异步加载/启动进度、行操作“使用/更多（查看信息、查看日志、停止）”、run/serve 冒烟测试（日志对话框）、多选缓存清理）、日志（`journalctl` 服务日志或指定模型的 serve 日志，支持返回服务日志、清空和原生“另存为”）、设置（服务启停、开机启动、国内镜像、共享缓存清理、主题、API 文档）。“使用”对话框显示目标 Serve 地址、OpenAI 兼容 curl 示例、API 文档、模型列表和本地控制台入口。模型详情只展示信息并提供启动/加载，使用/日志/停止仍保留在行操作中。通过 WebSocket（`/v1/ws`）接收系统、模型列表、存储、镜像和任务进度；HTTP 仅用于命令和按需查询（加载、拉取、日志、目录、清理）。加载进度（Bundle 同步、Python 运行时/venv、权重）和启动进度（serve 进程/健康检查）会显示 bundle 引用、当前阶段、文件/字节数和百分比；校验失败的下载会自动重试。下载串行执行：有任务进行中时客户端禁用加载/下载/启动按钮，重复 `/v1/pull` 返回 HTTP 409。「加载」会把 Bundle、Python 运行时/venv 和权重准备到就绪状态；就绪后才能「启动」，「停止」会结束该模型的 serve 进程。模型大小 = Bundle + 该模型运行时 + 权重；权重按 `source/repo@revision` 存储，可能被多个 bundle 版本共享（合计按权重 key 去重），而每个 bundle/版本有独立的运行时目录。设置中只统计/清理共享缓存（下载缓存 + 基础 Python + uv）；模型 Bundle/权重/运行时在「模型」页清理。

- 源码：`desktop/`；构建：`cargo build --release`（Rust MSVC 工具链，`cargo` 需在 PATH）。产物：`desktop/target/release/FlashServer.exe`（约 4.7MB）。
- 内存：约 110~125MB 工作集（GPU 上下文 + 中文字体 + egui 存储）。
- 主题：默认深色，可在设置中切换或用 `Ctrl+T`；启动时会直接应用已保存的主题（不受 Windows 应用主题影响），保存在 `%LOCALAPPDATA%\FlashServer\settings.json`。
- 破坏性操作（停止服务、禁用开机启动、停止模型、退出客户端）都会二次确认。
- 服务启停走 `wsl.exe`，不需要 UAC；开机启动开关调用 `flashserver-setup --enable-autostart/--disable-autostart`，会弹 UAC，且不会启动或停止服务。
- 服务状态与开机启动完全独立：停止不会禁用自启，启动不会启用自启，自启开关也不会启动/停止服务。耗时操作会显示模态进度遮罩，完成后弹出结果提示。
- 「API 文档」按钮打开当前 API 地址 + `/docs`（客户端从 `%LOCALAPPDATA%\FlashServer\api-url.txt` 读取端口）。
- 代码可跨平台编译；服务控制优先 Windows/WSL，Linux 走 `systemctl`（尽力而为），macOS 暂无 flashserver 后端。

## 国内镜像

设置 → 下载源（或 `POST /v1/mirror {"enabled":true}`）会为 bundle 准备和权重下载启用国内镜像：

- pip：`https://mirrors.aliyun.com/pypi/simple/`
- HuggingFace：`https://hf-mirror.com`
- GitHub：`https://gh-proxy.com/`
- FlashCLI 源码回退：`https://gitee.com/aodiansoft/flashcli.git`
- PyTorch wheel：SJTU 镜像（`mirror.TorchIndexURL`）

开关会写入 `~/.flashcli/mirror.env`，对新下载立即生效，不需要重启服务；`GET /v1/mirror` 返回当前状态。与 `install.sh --mirror` 使用同一组端点，不会修改 apt 源。服务停止或有下载/加载/启动任务时，桌面设置中的开关不可用。

## Windows UI 安装包

Windows 用户应优先使用 UI 安装包，而不是命令行：

```text
flashserver-setup-windows-amd64-v<version>.exe
```

安装包会以管理员权限运行，并通过实时进度页（`Step N of 8` + 当前阶段）驱动
`flashserver-setup`，不再静默等待。发布资产使用标准 OS/arch 名称并追加版本后缀，
版本同时体现在 release tag 和安装包元数据中：

```text
UI 安装包（管理员）
  → 解压 payload 到 %ProgramFiles%\FlashServer\payload
  → [1/8] 检查 WSL2；缺失时执行 `wsl --install --no-distribution` 自动启用
  → [2/8] 安装/注册 Ubuntu（旧版 Windows 10 回退到 DISM）
  → [3/8] 启用 systemd  → [4/8] 安装 Linux payload
  → [5/8] 写配置 + service → [6/8] 启动服务
  → [7/8] 创建 Windows 登录任务 → [8/8] 等待 /health
  → 再次检查 `systemctl is-active flashserver` 和 /health
  → 打开桌面客户端
```

如果启用 WSL2 需要重启 Windows，setup 会以退出码 **3** 结束。安装包会明确提示
需要重启，不启动客户端；完成页会要求在重启后再次运行安装包。第二次运行是幂等的，
会继续完成 Ubuntu/服务安装。成功后的完成页表示环境已通过就绪校验，而不仅是文件复制
完成；安装包会显示实际 API 地址。

Windows 可能把默认端口 `8790` 保留在 Hyper-V/WinNAT 的排除端口范围内。此时 setup
会自动选择下一个可用端口（`18790`、`28790` 等），在 WSL 内写
`0.0.0.0:<port>`，并把 Windows 侧地址写入
`%LOCALAPPDATA%\FlashServer\api-url.txt`。桌面客户端和安装器最终健康检查都会读取
该文件，因此客户端、安装器和 API 文档使用同一个端口。

安装包同时携带 `flashcli-bundle` Python 源码。setup 会把它解压到
`/usr/local/share/flashcli/flashcli-bundle`，并把 `FLASHCLI_BUNDLE_PIP_SPEC`
写入 `~/.flashcli/install.env`，因此创建 bundle 虚拟环境不依赖 WSL 内的
`git`/GitHub 访问。

自动化/排障时，`flashserver-setup --progress-file FILE` 会写入 `[n/8]` 行和最后的
`DONE <code>`（`0` 就绪、`3` 需要重启、`2` 出错）。完整跟踪（含
`wsl.exe`/`schtasks.exe` 输出）写入 `%USERPROFILE%\.flashcli\logs\setup.log`。

### 干净 Windows 虚拟机验证

使用 Windows 10 2004+/Windows 11 x64 虚拟机，能访问网络，并开启嵌套虚拟化
（VT-x/AMD-V）；没有嵌套虚拟化时 WSL2 无法启动。

1. 确认虚拟机是干净的：`wsl.exe --status` 失败，`wsl.exe -l -v` 中没有 Ubuntu。
2. 运行 `flashserver-setup-windows-amd64-v<version>.exe`。向导必须显示安装进度页；没有 WSL2 时第一次
   运行可能停在步骤 1 并提示重启。
3. 按提示重启后再次运行安装包。必须显示步骤 1-8，并以
   “FlashServer is installed and ready.” 结束。
4. 独立验证环境（安装器可能选择了 8790 以外的端口）：
   ```powershell
   wsl.exe -l -v
   wsl.exe -d Ubuntu -u root systemctl is-active flashserver   # active
   $url = (Get-Content "$env:LOCALAPPDATA\FlashServer\api-url.txt").Trim()
   (Invoke-WebRequest -UseBasicParsing "$url/health").StatusCode  # 200
   ```
5. 确认桌面客户端自动打开、总览页显示服务运行、开机启动已启用。再次运行安装包必须成功，
   且不会重复创建服务。

自动化场景仍可使用 CLI：

```powershell
flashserver-setup.exe --backend wsl
```

## 安装

Linux：

```bash
sudo flashserver-setup
```

安装到 `/usr/local/bin`，写入 `/etc/flashserver/config.json`，创建 `flashserver.service`，设置开机启动，并检查 `/health`。setup 会打印 `[n/N]` 步骤，并把完整跟踪（含 `wsl.exe`/`schtasks.exe` 输出）写入 `~/.flashcli/logs/setup.log`。

Windows（在管理员终端中运行；UI 安装包会自动提权）：

```powershell
flashserver-setup.exe
```

使用官方 Ubuntu WSL2（不制作自定义镜像）；WSL2 缺失时会自动启用
（`wsl --install --no-distribution`，旧版 Windows 10 回退到 DISM），在
`/etc/wsl.conf` 启用 systemd，在 WSL 内安装 Linux 二进制和
`flashserver.service`，并创建 `flashserver-wsl` 登录任务。没有 WSL2 的机器第一次
运行可能需要重启一次 Windows，之后再次运行 setup。

**磁盘位置。** 模型权重和 bundle 运行时都在 Ubuntu 虚拟磁盘（`ext4.vhdx`）里，默认位于系统盘，常见占用 20–40 GB。`--wsl-dir DIR` 会把发行版迁移到其他 NTFS 盘（WSL 没有安装时指定路径的参数，setup 会先安装，再在发行版停止时执行 `wsl --manage <distro> --move DIR`）。UI 安装包新增“WSL 数据目录”页面，默认与安装目录同级：`<安装目录的父目录>\FlashServerWSL`（例如安装到 `D:\software\FlashServer` 时默认 `D:\software\FlashServerWSL`）。之后删除数据**不会**自动缩小 VHDX：先用 `flashcli du` / `flashcli cache clean` / `flashcli bundle clean` 清理，再关闭 WSL 并压缩磁盘（`wsl --manage <distro> --set-sparse true`，或用 `diskpart` compact）。

**受限网络。** 当 `wsl --install` 无法访问 Microsoft Store 或 GitHub（或两分钟没有进度）时，setup 会自动从清华/中科大镜像（其次 `cloud-images.ubuntu.com`）下载 Ubuntu 24.04 官方 cloud rootfs，并用 `wsl --import` 导入到所选目录；也可以用 `--distro-rootfs FILE` 指定本地 rootfs 压缩包（离线安装）。

默认会下载匹配的 `flashcli-linux-<arch>` 和 `flashserver-linux-<arch>` release assets，并校验 `sha256sums.txt`。也可以用 `--bin-dir DIR` 使用本地资产，或用 `--release-version` / `--release-base` 固定 release 来源。

`--backend` 默认是 `auto`（Linux 为 `native`，Windows 为 `wsl`），通常不需要手动指定。`--dry-run` 只打印安装计划，不修改主机。`--no-service` 只安装二进制和配置，适用于容器或没有运行 systemd 的环境（之后手动运行 `flashserver --config ...`）。

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

- `max_loaded=0`：只按显存准入。
- WSL 默认使用 `addr=0.0.0.0:8790`（8790 被保留时 setup 可能选择其他端口），`public_host=localhost`、`serve_host=0.0.0.0`，通过 localhost forwarding 让 Windows 访问 WSL 服务。
- `token` 可选，默认不写。设置后除 `/health`、`/`、`/docs`、`/ui/*`、`/openapi.yaml` 外的 API 都需要 `Authorization: Bearer <token>` 或 `X-Flashcli-Token`。

## API

```text
GET  /health
GET  /v1/version
GET  /v1/models                 本地缓存模型 + 已启动实例 + serve 能力
GET  /v1/models/loaded
GET  /v1/storage                各区域唯一分配字节（硬链接只计一次）
GET  /v1/resources              GPU、已启动模型、槽位
GET  /v1/system                 OS/WSL/GPU/驱动/CUDA/SM/torch/CPU/内存/运行时长
GET  /v1/logs                   ?kind=server|model&ref=...&lines=N&since=unix
GET  /v1/logs/download          完整服务/模型日志附件
GET  /v1/gpu                    设备 + CUDA 进程
GET  /v1/gpu/history            ?seconds=N 最近 GPU+CPU 遥测采样
GET  /v1/system/history         /v1/gpu/history 的别名
GET  /v1/ws                     WebSocket：系统/模型/存储/镜像快照 + 任务进度
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/jobs/{id}/cancel        取消正在运行的任务（smoke/下载/加载）
POST /v1/models/load            {"ref":"...","async":true} → job_id（或 endpoint/pid/state）
POST /v1/models/unload          {"ref":"..."}
POST /v1/models/smoke           {"ref":"..."} run-only 冒烟测试 / 已启动 serve 请求测试
POST /v1/models/clean           {"refs":[...]} 清理本地 Bundle/权重
POST /v1/storage/clean          {"targets":["cache"]} 清理共享缓存（不含模型数据）
GET  /v1/catalog                ?q=&tag=&sort=updated|downloads&page=&page_size=
GET  /v1/catalog/tags
GET  /v1/catalog/{id}           仓库详情 + 版本列表
POST /v1/ui/chat                本地控制台代转：{"ref":"...","body":{...}}
GET  /docs                      HTML API 参考
GET  /openapi.yaml              OpenAPI 3.1 契约
GET  /                          内置本地控制台
```

`/v1/models/clean` 按 ref 清理模型相关数据：Bundle、运行时，以及没有其他引用时的权重；仍被其他缓存 ref 引用的共享权重/运行时保留（按剩余 bundle marker 计数）。`/v1/storage/clean` 只清理**共享缓存**（下载缓存、基础 Python、uv），不会删除 Bundle/权重/运行时。两者都返回释放字节数。

磁盘统计和清理路径选择位于共享的 `host` 包：`flashcli du` 与 `/v1/storage` 使用同一套唯一分配字节统计，`flashcli models list` 与 `/v1/models` 使用同一份模型数据，`flashcli bundle clean` 与 `/v1/models/clean` 使用同一套 ref 路径解析。

清理职责：

- **共享缓存** —— `~/.flashcli/cache`（下载/uv/FlashHub index）、`~/.flashcli/python`（基础解释器）、`~/.flashcli/tools`（uv）。可重新下载，不含模型数据。
  - CLI：`flashcli cache clean`
  - API：`POST /v1/storage/clean {"targets":["cache"]}`
- **模型数据** —— Bundle、权重（按 `source/repo@revision` 共享）和每个 bundle 的运行时。
  - CLI：`flashcli bundle clean <ref> --all`（单个 ref）、`flashcli bundle clean`（全部运行时）、`flashcli bundle clean --all`（全部 Bundle/权重/运行时）
  - API：`POST /v1/models/clean {"refs":[...]}`
  - 共享权重/运行时在还有其他缓存 ref 引用时保留；删除单个 ref 只是去掉它的 marker/引用。
- 桌面「设置 → 清理缓存」只清理共享缓存；模型相关清理在「模型」页多选清理，对应 `/v1/models/clean`。

旧 API 目标 `python`/`tools` 仍作为缓存子区域接受；`runtimes` 会被拒绝，请使用模型清理。

请求/响应 schema 以 [openapi.yaml](openapi.yaml) 为准（也通过 `/openapi.yaml` 提供）。

不提供 `/v1/infer`。`load` 成功后直接访问返回的 `endpoint`。

```bash
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

只有配置了 token 时才需要加 `-H "X-Flashcli-Token: $TOKEN"`。

`load` 要求 bundle 提供 `serve` 入口（会检查顶层 `entry`、`defaults.entry` 以及各环境条目）。只有 `run` 的 bundle（VLA 策略等）会在启动 serve 进程之前被拒绝，返回 `bundle "..." is run-only (no serve entry)`；这类模型请使用 `flashcli run <ref>`。桌面客户端的 FlashHub 页面只负责下载版本；下载后在“本地”页查看，没有 serve 入口的 bundle 会显示“仅 run”并隐藏加载按钮。

`POST /v1/models/smoke` 为已就绪模型启动异步冒烟任务：run-only 以低 CPU 优先级（`nice -n 10`）使用 manifest 默认参数执行 `flashcli run <ref>`（需要额外文件如图片的 bundle 会在日志中说明）；已启动的 serve 模型发送一次 OpenAI 兼容 chat 请求（`ping`）。桌面在 run 测试前会二次确认；输出和进度作为 `smoke` 任务通过 `/v1/ws` 实时推送，并追加到 `<ref>.smoke.log`。关闭或取消日志对话框、或退出客户端都会调用 `POST /v1/jobs/{id}/cancel` 终止任务，服务端也会在任务超时后停止。serve 测试要求模型已启动。

## 耗时参考

Windows 11 + 已有 WSL2 Ubuntu、RTX 4060 8GB、约 100 Mbit/s 网络下的参考值。首次准备占大头；后续命中缓存。

| 阶段 | 已缓存 | 首次 |
|---|---|---|
| UI 安装包 + setup（`[1/8]`…`[8/8]`） | 4–6 秒 | 无 WSL2/Ubuntu：再加 5–15 分钟，通常需重启一次 |
| Bundle 同步（FlashHub） | ~0 | 181 MiB @ ~4.7 MB/s ≈ 46 秒 |
| 权重下载（ModelScope/HF） | ~0 | ~7 GiB @ ~19 MB/s ≈ 6–7 分钟 |
| Python 3.12 + venv + torch/依赖 | ~0 | 约 2–5 分钟（取决于网络/缓存） |
| 模型加载 + autotune（pi05） | 约 40 秒 | 准备完成后相同 |
| 单次推理（pi05，10×7 actions） | 约 3.3–3.6 秒 | — |
| smoke 模型经 `/v1/models/load` | 约 2.5 秒 | — |

重复安装 + smoke 加载约 8 秒；安装 + 首次 pi05 推理约 10–15 分钟。实际随 bundle/权重大小和下载速度变化。

## 资源准入

以下情况 `load` 返回 `409 RESOURCE_EXHAUSTED`：

- `max_loaded > 0` 且已启动/正在启动数量达到上限；
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

无需卸载即可控制服务：

```powershell
flashserver-setup.exe --stop-service        # 停止服务并禁用开机启动（管理员）
flashserver-setup.exe --disable-autostart  # 仅禁用开机启动，服务继续运行（管理员）
flashserver-setup.exe --enable-autostart   # 仅启用开机启动，服务保持当前状态（管理员）
flashserver-setup.exe --start-service      # 启用开机启动并启动服务（管理员）
```

桌面客户端提供同样的操作；服务启停本身不需要提权，只有开机启动变更需要。`/v1/system` 会报告当前开机启动状态（`enabled`、`disabled` 或 `unknown`）。

## 卸载

```bash
sudo flashserver-setup --uninstall
```

移除 service、配置和 `flashserver` 二进制，保留 `FLASHCLI_HOME`（bundle、权重、运行时、缓存）、WSL 发行版和桌面设置。

可选清理参数：

| 参数 | 删除内容 |
|---|---|
| `--purge-models` | `FLASHCLI_HOME`（bundle、权重、运行时、缓存）以及解压出的 `flashcli-bundle` 源码 |
| `--remove-cli` | `/usr/local/bin/flashcli` |
| `--purge-settings` | 桌面客户端设置（`%LOCALAPPDATA%\FlashServer`）；Windows UI 卸载器还会删除 `%USERPROFILE%\.flashcli`（安装日志） |
| `--purge-distro` | Ubuntu WSL 发行版及其 `ext4.vhdx`（释放整个虚拟磁盘；Ubuntu 内所有数据丢失；仅 WSL） |

Windows UI 卸载器会在删除文件前用三个勾选项询问；静默卸载默认全部保留。若卸载时模型正在加载或启动，会先停止服务和相关任务（下载/加载状态保留在缓存中，下次安装可继续）。
