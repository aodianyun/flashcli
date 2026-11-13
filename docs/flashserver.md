# flashserver

<p align="right"><strong>English</strong> · <a href="flashserver.zh-CN.md">简体中文</a></p>

`flashserver` is a resident local model scheduler for a single PC. It owns model
lifecycle (prepare, load, start, stop) and GPU admission; inference still runs in
`flashcli serve` child processes.

```text
flashserver-setup  installs binaries and the boot service (systemd / WSL2)
flashserver        resident scheduler + local console API (default 127.0.0.1:8790)
flashcli serve     one model process, OpenAI-compatible API
```

Supported on Linux (systemd) and Windows (WSL2, official Ubuntu rootfs). There is
no remote mode. Authentication is **off by default** (single-user local daemon);
`--token` or `token` in the config enables it.

## Install

### Windows installer

Use `flashserver-setup-windows-amd64-v<version>.exe` (elevated). It drives
`flashserver-setup` behind a live progress page and opens the desktop client:

```text
[1/8] check/enable WSL2  → [2/8] register the distro → [3/8] enable systemd
[4/8] install Linux payload → [5/8] config + unit → [6/8] start service
[7/8] logon task + firewall rule → [8/8] wait for /health
```

- Exits with code **3** when Windows must restart; run it again afterwards.
  Re-running is idempotent and repairs the install without duplicating services.
- If Windows reserves `8790` (Hyper-V/WinNAT), setup picks the next free port and
  records it in `%LOCALAPPDATA%\FlashServer\api-url.txt`, which the client,
  installer, and API docs all read.
- New installs import `flashserver_ubuntu`; an existing `Ubuntu` that already has
  `/etc/flashserver/config.json` is reused. The active name is written to
  `%LOCALAPPDATA%\FlashServer\distro.txt`.
- New installs enable domestic mirrors and add the `FlashServer models` firewall
  rule (Private/Domain, all TCP by default).
- The error dialog shows an ASCII-only log tail; the full trace is
  `%LOCALAPPDATA%\FlashServer\logs\setup.log`.

### Linux

```bash
sudo flashserver-setup
```

Installs `/usr/local/bin/{flashcli,flashserver}`, writes
`/etc/flashserver/config.json` and `flashserver.service`, enables it at boot, and
checks `/health`.

### CLI options

| Flag | Purpose |
|---|---|
| `--backend auto\|native\|wsl` | Default `auto` (native on Linux, WSL on Windows) |
| `--bin-dir DIR` | Use local `flashcli-*` / `flashserver-*` assets instead of downloading |
| `--wsl-dir DIR` | Move the WSL distro to another NTFS drive |
| `--distro-rootfs FILE` | Import a local rootfs tarball (offline) |
| `--progress-file FILE` | Machine-readable `[n/8]` lines + `DONE <code>` (0 ready, 3 restart, 2 error) |
| `--no-service` | Binaries + config only (containers, no systemd) |
| `--dry-run` | Print the plan, change nothing |
| `--uninstall` / `--purge-*` | See [Service lifecycle](#service-lifecycle) |

### Verify

```bash
curl -s http://127.0.0.1:8790/health
```

On Windows the port may differ; read `%LOCALAPPDATA%\FlashServer\api-url.txt`.
Installer acceptance testing (clean VM) is in
[installer/windows/README.md](../installer/windows/README.md).

## Desktop client

The Windows package ships `FlashServer.exe` (Rust + egui/eframe, no WebView, no
console window). It streams live state over `/v1/ws` and uses HTTP for commands.

- **Overview**: GPU/VRAM/CPU/RAM cards and 5-minute charts, service and disk cards.
- **Models**: local cache plus FlashHub search; per-model Bundle / runtime /
  weights sizes; **Load** prepares the model and **Start** runs the serve process
  (**Stop** ends it); run/serve smoke tests with a live log; multi-select cleanup.
- **Logs**: service journal or per-model serve log, clear, and native Save-As.
- **Settings**: service start/stop, auto-start, domestic mirrors, shared-cache
  cleanup, WSL resources and firewall ports, theme (`Ctrl+T`), API docs.

Service state and auto-start are independent: stopping never disables auto-start,
and toggling auto-start never starts or stops the service. Destructive actions
ask for confirmation; long operations show a progress overlay. Settings live in
`%LOCALAPPDATA%\FlashServer\settings.json`.

## HTTP API

### Endpoints

```text
GET  /health
GET  /v1/version
GET  /v1/models                  cached models + loaded instances + serve capability
GET  /v1/models/loaded
GET  /v1/storage                 unique allocated bytes per area
GET  /v1/mirror                  domestic mirror state
POST /v1/mirror                  enable/disable mirrors for new downloads
GET  /v1/resources              GPU, loaded models, slot counts
GET  /v1/system                 OS/WSL/GPU/driver/CUDA/SM/torch/CPU/RAM/uptime
GET  /v1/logs                   ?kind=server|model&ref=...&lines=N&since=unix
GET  /v1/logs/download          full daemon/model log attachment
GET  /v1/gpu                    devices + CUDA processes
GET  /v1/gpu/history            ?seconds=N recent GPU+CPU telemetry samples
GET  /v1/ws                     WebSocket: snapshots + job progress
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/jobs/{id}/cancel        cancel a running job (smoke/download/load)
POST /v1/models/load            {"ref":"...","async":true} → job_id (or endpoint/pid/state)
POST /v1/models/unload          {"ref":"..."}
GET  /v1/models/options         ?ref=... manifest serve_options + saved values
PUT  /v1/models/options         {"ref":"...","host":"0.0.0.0","port":0,"options":{...}}
DELETE /v1/models/options       ?ref=... reset to defaults
POST /v1/models/smoke           {"ref":"..."} run-only smoke test or serve request test
POST /v1/models/clean           {"refs":[...]} remove local bundle/weight caches
POST /v1/storage/clean          {"targets":["cache"]} remove shared cache only
GET  /v1/catalog                ?q=&tag=&sort=updated|downloads&page=&page_size=
GET  /v1/catalog/tags
GET  /v1/catalog/{id}           repository detail + versions
POST /v1/ui/chat                local console helper: {"ref":"...","body":{...}}
GET  /docs                      HTML API reference
GET  /openapi.yaml              OpenAPI 3.1 contract
GET  /                          embedded local console
```

### Examples

```bash
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

Add `-H "X-Flashcli-Token: $TOKEN"` only when a token is configured. `load`
requires a `serve` entry: run-only bundles are rejected with
`bundle "..." is run-only (no serve entry)` — use `flashcli run` for those. There
is no `/v1/infer`; call the returned `endpoint` directly.

`POST /v1/models/smoke` runs `flashcli run` at low priority for run-only bundles
or one `ping` chat request for a started serve model; progress streams over
`/v1/ws` and is appended to `<ref>.smoke.log`.

### Cleanup

- **Shared cache** (`~/.flashcli/cache`, `python`, `tools`): `flashcli cache clean`
  or `POST /v1/storage/clean {"targets":["cache"]}`.
- **Model data** (bundle, per-bundle runtime, weights): `flashcli bundle clean …`
  or `POST /v1/models/clean {"refs":[...]}`. Shared weights/runtime are kept while
  another cached ref references them; both calls return freed bytes.

The authoritative schema is [openapi.yaml](openapi.yaml), also served at
`/openapi.yaml`.

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

## Configuration

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

- `max_loaded=0` admits by GPU memory only. A bundle that declares
  `resources.min_vram_mib` must fit free VRAM minus `min_free_vram_mib`, otherwise
  `load` returns `409 RESOURCE_EXHAUSTED`; slot limits also count starting models.
- WSL defaults: `addr=0.0.0.0:8790`, `public_host=localhost`,
  `serve_host=0.0.0.0` (Windows reaches the service through localhost forwarding).
- `token` is optional. When set, every path except `/health`, `/`, `/docs`,
  `/ui/*`, and `/openapi.yaml` requires `Authorization: Bearer <token>` or
  `X-Flashcli-Token`.
- Mirrors: Settings → 下载源 or `POST /v1/mirror {"enabled":true}` writes
  `~/.flashcli/mirror.env` (Aliyun pip, hf-mirror, gh-proxy, Gitee, SJTU torch)
  and applies to new downloads without restarting the service.

## Service lifecycle

On load, `flashserver` starts
`flashcli serve <ref> --host <serve_host> --port <allocated>` and waits for
`/health` before reporting `ready`; unload/shutdown stops the child. Linux uses a
systemd unit. WSL uses systemd plus the `flashserver-wsl` logon task, which starts
the distro and keeps it alive with a hidden `sleep infinity` session (otherwise
WSL stops the idle distro after about a minute).

```powershell
flashserver-setup.exe --stop-service        # stop service, disable auto-start
flashserver-setup.exe --disable-autostart   # keep running, disable auto-start
flashserver-setup.exe --enable-autostart    # enable auto-start, keep state
flashserver-setup.exe --start-service       # enable auto-start and start
```

```bash
sudo flashserver-setup --uninstall          # keeps model caches and the distro
```

| Uninstall flag | Removes |
|---|---|
| `--purge-models` | `FLASHCLI_HOME` (bundles, weights, runtimes, caches) and the extracted `flashcli-bundle` |
| `--remove-cli` | `/usr/local/bin/flashcli` |
| `--purge-settings` | desktop settings and the installer log (`%LOCALAPPDATA%\FlashServer`) |
| `--purge-distro` | the active WSL distro and its `ext4.vhdx` (all data inside; WSL only) |

The Windows uninstaller offers the same four cleanups plus select-all; a silent
uninstall keeps everything. Uninstalling during load/start stops the service and
its jobs first (cached state resumes on the next install).

## Notes and troubleshooting

- **Disk location**: weights and runtimes live in the WSL `ext4.vhdx`, defaulting
  to a sibling of the install directory (`%LOCALAPPDATA%\FlashServerWSL` under
  `Program Files`). Deleting data does not shrink it: clean with `flashcli du` /
  `flashcli cache clean` / `flashcli bundle clean`, then compact with
  `wsl --manage <distro> --set-sparse true` or `diskpart`.
- **Restricted networks**: when `wsl --install` cannot reach the Store/GitHub (or
  makes no progress for 90 seconds), setup imports the official Ubuntu 24.04
  rootfs from Tsinghua/USTC mirrors (then `cloud-images.ubuntu.com`); use
  `--distro-rootfs FILE` for offline installs.
- **Inspect inside WSL**:
  ```bash
  wsl -d flashserver_ubuntu
  ps -ef | grep '[f]lashcli.*serve'
  cat /proc/<pid>/cmdline | tr '\0' ' '; echo   # NUL-separated args
  cat /root/.flashcli/flashserver/serve-options.json
  journalctl -u flashserver -n 100 --no-pager
  ```
  The service runs as root (`FLASHCLI_HOME=/root/.flashcli` unless `--home` was
  used); the active distro name is in `%LOCALAPPDATA%\FlashServer\distro.txt`.
- **Timing** (RTX 4060 8 GB, ~100 Mbit/s): installer 4–6 s warm (5–15 min and one
  reboot when WSL2 is missing); bundle sync ~46 s per 181 MiB; weights ~6–7 min
  per ~7 GiB; Python + torch 2–5 min; model load ~40 s. A warm install plus load
  is about 8 s.
