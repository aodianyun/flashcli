# flashserver：桌面客户端

<p align="right"><a href="flashserver-desktop.md">English</a> · <strong>简体中文</strong></p>

Windows 安装包内置 `flashcli-desktop.exe`（Rust + egui/eframe，不用 WebView，无控制台窗口）。
实时状态走 `/v1/ws`，命令走 HTTP。安装与自行构建见
[../desktop/README.md](../desktop/README.md)。

## 功能

- **概览** —— GPU/显存/CPU/内存卡片与 5 分钟曲线、服务与磁盘卡片、当前 API 地址。
- **模型** —— 本地缓存 + FlashHub 搜索；分开展示 Bundle / 运行时 / 权重大小；
  加载、启动、停止；run/serve 冒烟测试带实时日志；多选清理。
- **应用** —— 左侧独立菜单页：封面卡片网格（名称、版本 · domain、简介，支持搜索与
  domain 过滤）+ 详情区展示能拿到的全部信息（组织/下载量/状态、中英文简介、
  supported OS/arch、各平台安装命令、依赖模型与 serve options、本地状态与模型、
  接入地址、manifest 版本字段），并支持安装/准备/启动/停止/卸载；数据全部来自
  `flashserver` 的 `/v1/apps`。点「安装」会先展示 manifest 里的安装脚本：只有选择
  「运行脚本并安装」才会执行（选择「跳过脚本安装」则只安装并启动模型），
  下载页类命令只展示供复制；守护进程收到缺少 `install_command`（`run`/`skip`）
  的安装请求会拒绝执行。安装/准备进度直接显示在详情区。
- **日志** —— 服务日志或单个模型的 serve 日志，可清空和另存为。
- **设置** —— 服务启停、开机启动、国内镜像、共享缓存清理、WSL 资源与防火墙端口、
  主题（`Ctrl+T`）、API 文档。

破坏性操作（停止服务、关闭开机启动、停止模型、退出）都会二次确认；耗时操作显示进度
遮罩并弹出结果提示。

## 模型生命周期

**加载**准备 Bundle、Python 运行时/venv 和权重；**启动**运行 serve 进程（只有就绪后
可用）；**停止**结束该进程。

- 下载串行执行：有任务进行中时禁用加载/下载/启动，重复 `POST /v1/pull` 返回 HTTP 409。
- 进度（Bundle 同步、运行时、权重、serve/健康检查）显示 bundle ref、阶段、字节数和
  百分比；校验失败的下载会自动重试。
- 模型大小 = Bundle + 该模型运行时 + 权重。权重按 `source/repo@revision` 跨版本共享
  （合计按权重 key 去重）；每个 bundle 版本有独立的运行时目录。
- 设置中只清理共享缓存（下载缓存、基础 Python、uv）；Bundle/权重/运行时在模型页清理。

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

## 设置与文件

- `%LOCALAPPDATA%\FlashServer\settings.json` —— 主题、防火墙端口、停止时是否关闭 WSL。
- `%LOCALAPPDATA%\FlashServer\distro.txt` —— 客户端控制的 WSL 发行版
  （`flashserver_ubuntu`，或旧 `Ubuntu`）。
- `%LOCALAPPDATA%\FlashServer\api-url.txt` —— 守护进程地址（可能不是默认端口）。

主题默认深色，启动时直接应用（不受 Windows 应用主题影响）。服务状态与开机启动相互
独立：停止不会关闭开机启动，开自启也不会启停服务。服务按钮走 `wsl.exe`（不需要 UAC）；
自启变更调用 `flashserver-setup` 并弹 UAC。5 秒健康检查保证显示状态准确。
