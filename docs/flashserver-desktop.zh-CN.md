# flashserver：桌面客户端

<p align="right"><a href="flashserver-desktop.md">English</a> · <strong>简体中文</strong></p>

Windows 安装包内置 `flashcli-desktop.exe`（Rust + egui/eframe，不用 WebView，无控制台窗口）。
实时状态走 `/v1/ws`，命令走 HTTP。安装与自行构建见
[../desktop/README.md](../desktop/README.md)。

## 功能

侧边栏顺序：**应用 → 模型 → 状态 → 日志 → 设置**。

- **状态** —— GPU/显存/CPU/内存卡片与 5 分钟曲线、服务与磁盘卡片、当前 API 地址。
- **模型** —— 本地缓存 + FlashHub 搜索；分开展示 Bundle / 运行时 / 权重大小；
  加载、启动、停止；run/serve 冒烟测试带实时日志；多选清理。已缓存且未运行的模型
  还提供 **更多 → 重新同步**，强制重新下载 bundle 树/权重
  （`/v1/pull {"force":true}`）；仅作为可变 revision 的修复手段，正常更新应发布新的
  bundle 版本。
- **应用** —— 左侧独立菜单页：封面卡片网格（上方封面按原图比例完整显示，下方名称、
  版本 · domain、简介；搜索与 domain 过滤各占一行；分类顺序固定为
  全部、通用Agent、专用Agent、音视频制作，其余 domain 按字母序追加）+ 详情区展示能拿到的信息
  （组织/下载量/状态、简介、supported OS/arch、各平台安装命令、依赖模型与
  serve options、本地状态与模型、接入地址），并支持安装/启动/停止/卸载；数据全部来自
  `flashserver` 的 `/v1/apps`。应用列表和 manifest 每次请求都从 FlashHub 实时获取
  （本地不缓存 manifest）；桌面端在内存中保留当前列表/详情，修改 manifest 后请点
  「刷新」或重新选择应用。应用版本不可变，应发布新版本而不是原地修改。点「安装」会先展示
  manifest 的安装步骤：脚本在
  **客户端 OS 本地执行**（Windows 应用装在 Windows，不在 WSL；其他系统用 `sh -c`），
  安装包 URL（.exe/.msi/.dmg/.pkg）在确认后**下载并运行**，普通页面链接在浏览器打开；
  只有选择「运行脚本并安装 / 下载并安装」才会执行，「跳过」则只准备模型。安装只负责
  安装应用并**准备**模型 bundle，**不会启动**模型；「启动」是单独操作，也是执行
  `setup.scripts` 的时机。守护进程收到缺少 `install_command`（`client`/`run`/`skip`）
  的安装请求会拒绝执行。平台校验与命令选择使用客户端 OS/arch
  （`client_os`/`client_arch`）。若 manifest 声明 `setup.scripts`，手动启动时会
  弹出确认框选择要执行的脚本；模型就绪后按顺序执行，先校验 `sha256`，并把客户端 home
  映射到 WSL 写入应用配置。确认的脚本定义、key 与客户端 home 会被保存；daemon 重启恢复
  应用后会自动执行同一组脚本（无需重新拉取 manifest），使用新接入地址。某个脚本失败会
  记录日志、显示在应用上并停止后续脚本；已就绪的应用还提供「应用配置」按钮，可只重跑
  脚本而不重启模型。最近一次启动输出会保存在应用上（`last_log`），恢复后的应用
  仍能看到最近日志和「完整日志」。安装进度直接显示在详情区；同一时间只安装一个应用：
  安装中的卡片显示「安装中 · 阶段 xx%」与进度条，页面顶部显示安装横幅，其他应用的操作被禁用。
  domain 分类取自接口返回，不再写死。
  卸载会停止该应用启动的模型并删除安装记录；勾选「同时删除模型缓存」会额外删除该应用的
  bundle/权重缓存（重新安装需重新下载），但不会卸载应用自身安装的程序与数据。
  日志分三类：应用安装/准备日志（详情区显示最近 8 行，点「查看完整日志」看全部、可复制）、
  模型 serve 日志（模型页 → 更多 → 查看日志，可另存为）、服务日志（左侧「日志」页）。
- **日志** —— 服务日志（左侧「日志」页，可清空/另存为）与模型 serve 日志
  （模型页 → 更多 → 查看日志）。服务日志包含 API 调用（方法/路径/状态/耗时，敏感字段
  脱敏）、后台任务步骤（应用安装/启动/停止、模型加载/pull/冒烟）、setup 脚本输出、
  清理/卸载，并持久化到 `~/.flashcli/logs/flashserver.log`（4 MiB 轮转，保留 `.1`），
  重启后仍可查看。页面首次加载后通过 `/v1/ws` 实时追加新日志；成功的状态/日志轮询请求
  不会写入日志。应用详情另有最近启动日志与「查看完整日志」。
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
内存 50%、全部逻辑 CPU、Swap 25%）。`autoMemoryReclaim=gradual` 默认开启：空闲时把
可回收的 page cache 还给 Windows，避免 WSL 长时间占着内存；代价是之后再次加载模型可能
需要重新读盘（稍慢）。这些设置对所有 WSL2 发行版生效，并需要重启 WSL。镜像网络需要
Windows 11 22H2+。公网访问还需要额外的 Public 规则和路由器端口映射；不要在没有
token 的情况下直接暴露 API。

## 设置与文件

- `%LOCALAPPDATA%\flashcli-desktop\settings.json` —— 主题、防火墙端口、停止时是否关闭 WSL。
- `%LOCALAPPDATA%\flashcli-desktop\distro.txt` —— 客户端控制的 WSL 发行版
  （`flashserver_ubuntu`，或旧 `Ubuntu`）。
- `%LOCALAPPDATA%\flashcli-desktop\api-url.txt` —— 守护进程地址（可能不是默认端口）。

主题默认深色，启动时直接应用（不受 Windows 应用主题影响）。服务状态与开机启动相互
独立：停止不会关闭开机启动，开自启也不会启停服务。服务按钮走 `wsl.exe`（不需要 UAC）；
自启变更调用 `flashserver-setup` 并弹 UAC。5 秒健康检查保证显示状态准确。
