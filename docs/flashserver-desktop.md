# flashserver: desktop client

<p align="right"><strong>English</strong> · <a href="flashserver-desktop.zh-CN.md">简体中文</a></p>

The Windows package ships `FlashServer.exe`, a Rust + egui/eframe client (no
WebView, no console window). It streams live state over `/v1/ws` and uses HTTP
for commands. Install/build details are in [../desktop/README.md](../desktop/README.md).

## Features

- **Overview** — GPU/VRAM/CPU/RAM cards and 5-minute charts, service and disk
  cards, current API URL.
- **Models** — local cache plus FlashHub search; per-model Bundle / runtime /
  weights sizes; load, start, stop; run/serve smoke tests with a live log;
  multi-select cache cleanup.
- **Logs** — service journal or a model's serve log, with clear and native
  Save-As.
- **Settings** — service start/stop, auto-start, domestic mirrors, shared-cache
  cleanup, WSL resources and firewall ports, theme (`Ctrl+T`), API docs.

Destructive actions (stop service, disable auto-start, stop model, quit) ask for
confirmation; long operations show a progress overlay and a result toast.

## Model lifecycle

**Load** prepares the bundle, Python runtime/venv, and weights; **Start** runs the
serve process and is enabled only when the model is ready; **Stop** ends it.

- Downloads are serialized: while a job runs, load/download/start actions are
  disabled and a concurrent `POST /v1/pull` returns HTTP 409.
- Progress (bundle sync, runtime, weights, serve/health) shows the bundle ref,
  phase, byte counts, and percentage; failed checksum downloads retry.
- Model size = Bundle + that model's runtime + weights. Weights are shared by
  `source/repo@revision` across bundle versions (totals de-duplicate by weights
  key); each bundle version has its own runtime directory.
- Settings cleans only the shared cache (downloads, base Python, uv). Bundle,
  weights, and runtime cleanup lives on the Models page.

## Startup parameters and LAN access

Per-model parameters come from the bundle's `serve_options` in
`flashcli-bundle.json` (including v4 environment overlays), plus a host and port:

- `host`: `0.0.0.0` binds all interfaces, `127.0.0.1` is local-only.
- `port`: `0` picks any free port; fixed ports are checked for conflicts.
- Empty option values use bundle defaults; non-empty values are appended as
  `--flag value` to `flashcli serve`. Host-level `host`/`ip`/`port` entries are
  represented by the fields above and are not added twice.
- Values are stored in `$FLASHCLI_HOME/flashserver/serve-options.json` (CLI, API,
  and desktop share it); saving while a model runs takes effect on the next start.

Windows localhost forwarding makes `host=0.0.0.0` reachable at
`http://localhost:<port>`. LAN/public access needs mirrored networking:

1. Settings → WSL 资源 → 局域网访问 writes `networkingMode=mirrored` to
   `%USERPROFILE%\.wslconfig`.
2. The client requests UAC and allows the configured inbound TCP ports (empty =
   all TCP, e.g. `18000-18999`) on the Private/Domain profiles.
3. Applying restarts WSL and `flashserver`; running models are interrupted.

The same panel edits `.wslconfig` `memory`/`processors`/`swap` (empty = WSL
defaults: 50% RAM, all logical CPUs, 25% swap). These apply to every WSL2 distro.
Mirrored networking requires Windows 11 22H2+. Public internet access additionally
needs a Public-profile rule and router port forwarding; never expose the API
without a token.

## Settings and files

- `%LOCALAPPDATA%\FlashServer\settings.json` — theme, firewall ports, stop-WSL
  behavior.
- `%LOCALAPPDATA%\FlashServer\distro.txt` — the WSL distro the client controls
  (`flashserver_ubuntu`, or a legacy `Ubuntu`).
- `%LOCALAPPDATA%\FlashServer\api-url.txt` — the daemon URL, including a
  non-default port.

Theme is dark by default and applied at startup (independent of the Windows app
theme). Service state and auto-start are independent: stopping never disables
auto-start, and toggling auto-start never starts or stops the service. Service
buttons use `wsl.exe` (no UAC); auto-start changes call `flashserver-setup` and
prompt for UAC. A 5-second health watchdog keeps the displayed state accurate.
