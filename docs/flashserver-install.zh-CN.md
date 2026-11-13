# flashserver：安装与运维

<p align="right"><a href="flashserver-install.md">English</a> · <strong>简体中文</strong></p>

常驻调度器的安装、配置、运行与卸载。功能概述见
[flashserver.zh-CN.md](flashserver.zh-CN.md)。

## 安装

### Windows 安装包

使用 `flashserver-setup-windows-amd64-v<version>.exe`（管理员）。它以实时进度页驱动
`flashserver-setup`，完成后打开桌面客户端：

```text
[1/8] 检查/启用 WSL2 → [2/8] 注册发行版 → [3/8] 启用 systemd
[4/8] 安装 Linux payload → [5/8] 写配置 + 服务 → [6/8] 启动服务
[7/8] 登录任务 + 防火墙规则 → [8/8] 等待 /health
```

- 退出码 **3** 表示需要重启 Windows，重启后再运行一次。重复运行是幂等的，用于修复
  安装，不会重复创建服务。
- 若 `8790` 被 Windows 保留（Hyper-V/WinNAT），setup 自动选下一个空闲端口并写入
  `%LOCALAPPDATA%\FlashServer\api-url.txt`；客户端、安装器和 API 文档都读取该文件。
- 新安装把发行版导入为 `flashserver_ubuntu`；已有 `/etc/flashserver/config.json` 的
  旧 `Ubuntu` 会被复用。实际名称在 `%LOCALAPPDATA%\FlashServer\distro.txt`。
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
| `--bin-dir DIR` | 使用本地未加版本号的构建产物（`flashcli` / `flashserver` 或 `flashcli-<os>-<arch>`），不联网下载 |
| `--wsl-dir DIR` | 把 WSL 发行版迁移到其他 NTFS 盘 |
| `--distro-rootfs FILE` | 导入本地 rootfs 压缩包（离线安装） |
| `--progress-file FILE` | 机器可读的 `[n/8]` 行 + `DONE <code>`（0 就绪、3 需重启、2 出错） |
| `--no-service` | 只装二进制和配置（容器或无 systemd 环境） |
| `--dry-run` | 只打印计划，不修改主机 |
| `--uninstall` / `--purge-*` | 见 [卸载](#卸载) |

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

- `max_loaded=0` 只按显存准入。bundle 的 `resources.min_vram_mib` 必须能放进
  「空闲显存 − `min_free_vram_mib`」，否则 `load` 返回 `409 RESOURCE_EXHAUSTED`；
  槽位上限也把正在启动的模型计入。
- WSL 默认：`addr=0.0.0.0:8790`、`public_host=localhost`、`serve_host=0.0.0.0`
  （Windows 通过 localhost 转发访问服务）。
- `token` 可选。设置后除 `/health`、`/`、`/docs`、`/ui/*`、`/openapi.yaml` 外的所有
  路径都需要 `Authorization: Bearer <token>` 或 `X-Flashcli-Token`。
- 镜像：`POST /v1/mirror {"enabled":true}`（或桌面开关）会写
  `~/.flashcli/mirror.env`（阿里云 pip、hf-mirror、gh-proxy、Gitee、SJTU torch），
  对新下载立即生效，不需要重启服务。

## 服务生命周期

`load` 时 `flashserver` 启动
`flashcli serve <ref> --host <serve_host> --port <allocated>`，等 `/health` 通过后才
报告 `ready`；`unload`/退出会停止该子进程。

Linux 使用 systemd 单元。WSL 使用 systemd 加 `flashserver-wsl` 登录任务：任务启动
发行版并用隐藏的 `sleep infinity` 会话保持常驻（否则 WSL 在空闲约一分钟后会停掉
发行版）。

```powershell
flashserver-setup.exe --stop-service        # 停止服务并关闭开机启动
flashserver-setup.exe --disable-autostart   # 保持运行，仅关闭开机启动
flashserver-setup.exe --enable-autostart    # 仅开启开机启动，保持当前状态
flashserver-setup.exe --start-service       # 开启开机启动并启动服务
```

服务状态与开机启动相互独立：停止不会关闭开机启动，开自启也不会启停服务。
`/v1/system` 报告当前自启状态（`enabled`、`disabled`、`unknown`）。

## 卸载

```bash
sudo flashserver-setup --uninstall          # 保留模型缓存和发行版
```

| 参数 | 删除内容 |
|---|---|
| `--purge-models` | `FLASHCLI_HOME`（bundle、权重、运行时、缓存）以及解压出的 `flashcli-bundle` |
| `--remove-cli` | `/usr/local/bin/flashcli` |
| `--purge-settings` | 桌面设置和安装日志（`%LOCALAPPDATA%\FlashServer`） |
| `--purge-distro` | 当前 WSL 发行版及其 `ext4.vhdx`（内部数据全部丢失；仅 WSL） |

Windows 卸载器提供同样的四项清理和全选；静默卸载保留全部数据。卸载时若模型正在
加载或启动，会先停止服务和相关任务（缓存状态会在下次安装后继续）。

## 存储与网络

- **磁盘位置**：权重和运行时在 WSL 的 `ext4.vhdx` 里，默认与安装目录同级
  （安装在 `Program Files` 下时为 `%LOCALAPPDATA%\FlashServerWSL`）。删除数据不会
  自动缩小：先用 `flashcli du` / `flashcli cache clean` / `flashcli bundle clean`
  清理，再用 `wsl --manage <distro> --set-sparse true` 或 `diskpart` 压缩。
- **受限网络**：`wsl --install` 无法访问 Store/GitHub（或 90 秒无进度）时，setup 从
  清华/中科大镜像（其次 `cloud-images.ubuntu.com`）导入官方 Ubuntu 24.04 rootfs；
  离线安装可用 `--distro-rootfs FILE`。
- **端口**：守护进程默认只监听本机。局域网/公网访问需要镜像网络和防火墙端口，见
  [flashserver-desktop.zh-CN.md](flashserver-desktop.zh-CN.md#启动参数与局域网访问)。

## 排障

在 WSL 内检查实际进程：

```bash
wsl -d flashserver_ubuntu
ps -ef | grep '[f]lashcli.*serve'
cat /proc/<pid>/cmdline | tr '\0' ' '; echo   # 参数以 NUL 分隔
cat /root/.flashcli/flashserver/serve-options.json
journalctl -u flashserver -n 100 --no-pager
```

服务以 root 运行（除非用了 `--home`，`FLASHCLI_HOME=/root/.flashcli`）；实际发行版
名称见 `%LOCALAPPDATA%\FlashServer\distro.txt`。安装与守护进程日志：Windows 在
`%LOCALAPPDATA%\FlashServer\logs\setup.log`，发行版内在 `~/.flashcli/logs`。

耗时参考（RTX 4060 8 GB、约 100 Mbit/s）：安装器已缓存 4–6 秒（缺少 WSL2 时
5–15 分钟并通常需重启一次）；Bundle 同步约 46 秒 / 181 MiB；权重约 6–7 分钟 /
~7 GiB；Python + torch 2–5 分钟；模型加载约 40 秒。
