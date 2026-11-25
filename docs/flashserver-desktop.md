# flashserver: desktop client

<p align="right"><strong>English</strong> · <a href="flashserver-desktop.zh-CN.md">简体中文</a></p>

The Windows package ships `flashcli-desktop.exe`, a Rust + egui/eframe client (no
WebView, no console window). It streams live state over `/api/v1/ws` and uses HTTP
for commands. Install/build details are in [../desktop/README.md](../desktop/README.md).

## Features

Sidebar order: **应用 → 模型 → 状态 → 日志 → 设置**.

- **Status** — GPU/VRAM/CPU/RAM cards and 5-minute charts, service and disk
  cards, current API URL.
- **Models** — local cache plus FlashHub search; per-model Bundle / runtime /
  weights sizes; disk **preload/unload**; resident state from the scheduler;
  run/serve smoke tests with a live log; multi-select cache cleanup. A cached
  model also offers **更多 → 重新同步**, which force-re-downloads its bundle
  tree/weights (`/api/v1/pull {"force":true}`); use it only as a repair for a
  mutable revision, not instead of a new bundle version. Inference is served by
  the gateway and the scheduler starts residents on demand; the desktop does not
  offer application-level model start/stop.
- **应用** — a sidebar page for FlashHub apps: a cover-card grid
  (name, version · domain, description; search and domain filters; category chips
  are ordered 全部, 通用Agent, 专用Agent, 音视频制作, then extra domains
  alphabetically) plus a detail pane with all available metadata —
  organization/downloads/status, description, supported OS/arch, every platform
  install command, dependency bundles and serve options, local state/models,
  gateway connection URL — and install/activate/deactivate/uninstall through
  `/api/v1/apps`. 安装 first shows the manifest install step: a script runs, or an
  installer URL is downloaded and run, on the client OS (a Windows app installs
  on Windows, not in WSL) — only after 运行脚本并安装 / 下载并安装; 跳过 installs the
  models without it, and a plain page URL opens in the browser. Install only
  installs the application and **prepares** the model bundles; it does not start
  them. 启用 is a separate action that writes the flashserver gateway connection
  (`http://<host>:8790/v1`) and runs `setup.scripts`; it never starts a model.
  The daemon rejects an install without an explicit decision
  (`install_command: client | run | skip`). Progress streams into the detail pane.
  When the manifest declares `setup.scripts`, 启用 asks which scripts to run; the
  daemon runs them in manifest order, verifies `sha256`, and maps the client home
  into WSL so the application's real config is written. The confirmed
  definitions, keys and client home are saved. A failure is logged, shown on the
  app, and stops the remaining scripts; an active app also offers **应用配置** to
  re-run the scripts. The last activation output is kept on the app (`last_log`),
  so the detail pane still shows recent lines and a full-log entry.
  One application installs at a time: while a job runs, its card shows
  `安装中 · 阶段 xx%` with a bar, a banner appears above the grid, and the other
  apps' actions are disabled.
  Everything is served by `flashserver` (`/api/v1/apps`). The application list and
  manifests are fetched from FlashHub on every request (no local manifest
  cache); the desktop keeps the current list/detail in memory, so use 刷新 or
  reselect after a manifest change. App versions are immutable: publish a new
  version instead of editing one in place.
  Uninstall removes the install record; the optional
  "同时删除模型缓存" checkbox also deletes that app's bundle/weight caches
  (a reinstall downloads them again). The app's own installed program and its
  data are never removed.
- **Logs** — the service log (日志 page, clear / Save-As) and a model's serve
  log (模型 → 更多 → 查看日志, with 另存为). The service log covers API calls
  (method/path/status/duration, credentials redacted), background job steps
  (app install/activate, model preload/unload/pull/smoke), setup-script output
  and clean/uninstall, and is persisted to `~/.flashcli/logs/flashserver.log`
  (4 MiB rotation with a `.1` backup), so it survives a daemon restart. The
  page loads once and then appends new lines over `/api/v1/ws`; successful status
  and log polling requests are not written to the log. The app detail also
  keeps the last activation log with its own 查看完整日志 entry.
- **Settings** — service start/stop, auto-start, domestic mirrors, shared-cache
  cleanup, WSL resources and firewall ports, theme (`Ctrl+T`), API docs.

Destructive actions (stop service, disable auto-start, unload model, quit) ask for
confirmation; long operations show a progress overlay and a result toast.

## Model lifecycle

**Preload** downloads the bundle/weights and prepares the runtime/venv without
starting a serve process. **Unload** stops the resident (busy models return
`409 model_busy` unless forced) and deletes the disk assets. Resident start/stop
is owned by the flashserver scheduler; the desktop only shows the state and calls
the gateway for inference.


- Downloads are serialized: while a job runs, load/download/start actions are
  disabled and a concurrent `POST /api/v1/pull` returns HTTP 409.
- Progress (bundle sync, runtime, weights, serve/health) shows the bundle ref,
  phase, byte counts, and percentage; failed checksum downloads retry.
- Model size = Bundle + that model's runtime + weights. Weights are shared by
  `source/repo@revision` across bundle versions (totals de-duplicate by weights
  key); each bundle version has its own runtime directory.
- Settings cleans only the shared cache (downloads, base Python, uv). Bundle,
  weights, and runtime cleanup lives on the Models page.

## Startup parameters and LAN access

Per-model parameters come from the bundle's `serve_options` in
`flashcli-bundle.json` (including v4 environment overlays), plus a port:

- Child serve processes always bind loopback (`127.0.0.1`); a saved LAN host is
  ignored because child endpoints are internal to the gateway.
- `port`: `0` picks any free port; fixed ports are checked for conflicts.
- Empty option values use bundle defaults; non-empty values are appended as
  `--flag value` to `flashcli serve`. Host-level `host`/`ip`/`port` entries are
  represented by the fields above and are not added twice.
- Values are stored in `$FLASHCLI_HOME/flashserver/serve-options.json` (CLI, API,
  and desktop share it); saving takes effect on the next resident start.

Only the flashserver gateway (`addr`, `public_host`, optional `token`) is a LAN
surface. To reach it from other devices:

1. Settings → WSL 资源 → 局域网访问 writes `networkingMode=mirrored` to
   `%USERPROFILE%\.wslconfig`.
2. The client requests UAC and allows the configured inbound TCP ports (empty =
   all TCP, e.g. `18000-18999`) on the Private/Domain profiles.
3. Applying restarts WSL and `flashserver`; residents are stopped and restart on
   demand.

The same panel edits `.wslconfig` `memory`/`processors`/`swap` (empty = WSL
defaults: 50% RAM, all logical CPUs, 25% swap). `autoMemoryReclaim=gradual` is
on by default: WSL returns idle page cache to Windows instead of holding it for
the whole session (reusable pages, so a later model load may read them from disk
again). These apply to every WSL2 distro and need a WSL restart. Mirrored
networking requires Windows 11 22H2+. Public internet access additionally
needs a Public-profile rule and router port forwarding; never expose the API
without a token.

## Settings and files

- `%LOCALAPPDATA%\flashcli-desktop\settings.json` — theme, firewall ports, stop-WSL
  behavior.
- `%LOCALAPPDATA%\flashcli-desktop\distro.txt` — the WSL distro the client controls
  (`flashserver_ubuntu`, or a legacy `Ubuntu`).
- `%LOCALAPPDATA%\flashcli-desktop\api-url.txt` — the daemon URL, including a
  non-default port.

Theme is dark by default and applied at startup (independent of the Windows app
theme). Service state and auto-start are independent: stopping never disables
auto-start, and toggling auto-start never starts or stops the service. Service
buttons use `wsl.exe` (no UAC); auto-start changes call `flashserver-setup` and
prompt for UAC. A 5-second health watchdog keeps the displayed state accurate.
