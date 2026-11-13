# flashserver

<p align="right"><strong>English</strong> · <a href="flashserver.zh-CN.md">简体中文</a></p>

`flashserver` is the resident local model scheduler for personal PCs. It owns model lifecycle and resource admission; inference stays in `flashcli serve` child processes.

```text
flashserver-setup  → installs binaries + service
flashserver        → resident scheduler + HTTP API
flashcli serve     → one model process, OpenAI-compatible API
```

## Scope

- Linux native and Windows WSL2 (official Ubuntu distribution).
- No remote mode. Inference endpoints are returned to clients; the local console uses a same-origin helper (`/v1/ui/chat`) to avoid browser CORS.
- Authentication is **off by default** (single-user local daemon). Pass `--token`/write `token` in the config to require `X-Flashcli-Token` or `Authorization: Bearer` on API calls.
- `flashserver` must run as a boot-started service. It schedules multiple models when GPU memory and the configured slot limit allow it.

## Local console

Open `http://localhost:8790/` after installation (the default port; on Windows
the installer may select a different free port, see "Windows UI installer"). The embedded console shows GPU/VRAM, utilization, temperature, clocks, power (when the driver exposes it), CUDA/SM/torch environment, CUDA process memory (native Linux; WSL usually does not expose it), CPU model/cores/load/per-core utilization, RAM/swap, 5-minute GPU and CPU charts, service uptime, cached models, loaded models, logs, and can load/unload models and test chat. It is served by the same binary (no extra assets or Node build). The HTTP contract is published at `/openapi.yaml`, an HTML reference is served at `/docs`, and the source is mirrored in [openapi.yaml](openapi.yaml). Live clients can use `GET /v1/ws` (system snapshot 1 Hz + job progress). `GET /v1/catalog` proxies the public FlashHub catalog (search, categories, versions) and `GET /v1/logs/download` returns the full daemon journal.

## Desktop client

The Windows installer ships `FlashServer.exe`, a Rust + egui/eframe desktop client (no WebView, no console window): overview (card layout with GPU/CPU environment and 0-100 charts, compact two-row service/disk cards, flat GPU/VRAM/CPU/RAM status bar), models (local cache plus on-demand FlashHub search/categories/versions, separate Bundle/runtime/weight sizes, ready and started states, async load/start progress, row actions for info/model logs/use/start/stop plus run/serve smoke tests with a log dialog, and multi-select cache cleanup), logs (`journalctl` tail or per-model serve logs with clear and native Save-As), and settings (service start/stop, auto-start, domestic-mirror toggle, shared-cache cleanup with per-item sizes, theme, API docs). It talks to the daemon over WebSocket (`/v1/ws`), which streams system snapshots, model/storage/mirror state, and job progress; HTTP is used only for commands and on-demand data (load, pull, logs, catalog, cleanup). Load progress (bundle sync, Python runtime/venv, weights) and start progress (serve process/health) show the bundle ref, phase, file/byte counts and percentage; downloads retry on checksum mismatch. Downloads are serialized: the client disables load/download/start actions while a job is active, and a concurrent `/v1/pull` returns HTTP 409. "加载" prepares the bundle, Python runtime/venv and weights to a ready state; only a ready model can be started with "启动", and "停止" ends its serve process. Model size is Bundle + per-model runtime + weights; weights are stored by `source/repo@revision` and may be shared across bundle versions (the total de-dupes by weights key), while each bundle/version has its own runtime directory. Settings groups the shared cache (downloads + base Python + uv); model bundles/weights/runtimes are cleaned from the Models page.

- Source: `desktop/`; build with `cargo build --release` (Rust MSVC toolchain; put `cargo` on PATH). Output: `desktop/target/release/FlashServer.exe` (~4.7 MB).
- Memory: ~110-125 MB working set (GPU context + CJK font + egui stores).
- Theme: dark by default, switched in Settings or with `Ctrl+T`; the saved choice is applied at startup (independent of the Windows app theme) and stored in `%LOCALAPPDATA%\FlashServer\settings.json`.
- Domestic mirrors: Settings → 下载源 enables pip (Aliyun), HuggingFace (`hf-mirror.com`), GitHub (`gh-proxy.com`) and the Gitee `flashcli` repo. It writes `~/.flashcli/mirror.env` and applies to new downloads immediately; apt sources are not changed.
- Destructive actions (stop service, disable auto-start, stop model, quit) ask for confirmation. "停止服务" can optionally terminate the selected WSL distribution (`distro.txt`, default `flashserver_ubuntu`; legacy installs use `Ubuntu`).
- Service buttons use `wsl.exe` (no UAC). Starting the service boots the distro if stopped, waits for systemd, retries `systemctl start`, and verifies `/health`; a 5-second watchdog updates the running state. The auto-start toggle calls `flashserver-setup --enable-autostart/--disable-autostart`, which enables/disables the `flashserver-wsl` logon task (the WSL auto-start) and therefore prompts for UAC; it does not start or stop the service.
- Service state and auto-start are independent: stopping never disables auto-start, starting never enables it, and auto-start changes never start/stop the service. Long operations show a modal progress overlay and a result toast.
- New Windows installs open the model firewall ports and enable domestic mirrors by default. The firewall is editable under **Settings → WSL 资源 → 防火墙端口**; empty means all TCP ports.
- API docs open the configured API URL + `/docs` (the client reads the port from `%LOCALAPPDATA%\FlashServer\api-url.txt`).
- The code compiles cross-platform; service control is wired for Windows/WSL first, Linux uses `systemctl` (best effort) and macOS has no flashserver backend yet.

## Domestic mirrors

Settings → 下载源 (or `POST /v1/mirror {"enabled":true}`) enables China-friendly endpoints for bundle preparation and weight downloads:

- pip: `https://mirrors.aliyun.com/pypi/simple/`
- HuggingFace: `https://hf-mirror.com`
- GitHub: `https://gh-proxy.com/`
- FlashCLI source fallback: `https://gitee.com/aodiansoft/flashcli.git`
- PyTorch wheels: SJTU mirror (`mirror.TorchIndexURL`)

The toggle writes `~/.flashcli/mirror.env` and applies to new downloads without restarting the service. `GET /v1/mirror` returns the current state. Setup enables this file by default on new installs; the desktop can disable it later. This is the same endpoint set as `install.sh --mirror`; it does not rewrite apt sources. The desktop setting is disabled while the service is stopped or a download/load/start job is running.

## Windows UI installer

Windows users should use the UI installer rather than the CLI:

```text
flashserver-setup-windows-amd64-v<version>.exe
```

It runs elevated and drives `flashserver-setup` behind a live progress page
(`Step N of 8`, with the current phase) instead of a silent wait. The release
asset keeps the standard OS/arch name plus a version suffix; the version is
also in the release tag and installer metadata:

```text
UI installer (admin)
  → extract payload to %ProgramFiles%\FlashServer\payload
  → [1/8] check WSL2; enable it with `wsl --install --no-distribution` when missing
  → [2/8] register the FlashServer distro: new installs import the Ubuntu rootfs as `flashserver_ubuntu`; legacy `Ubuntu` with a FlashServer config is reused
  → [3/8] enable systemd  → [4/8] install Linux payload
  → [5/8] write config + unit → [6/8] start service
  → [7/8] create the Windows logon task + model firewall rule → [8/8] wait for /health
  → verify readiness in the setup engine, then launch the desktop client
```

If enabling WSL2 requires a Windows restart, setup exits with code **3**. The
installer explains that a restart is required, keeps the client closed, and the
finished page asks you to run Setup again after restarting. The second run is
idempotent and completes the FlashServer distro/service installation. On success
the finished page means the environment was verified ready by the setup engine,
not just that files were copied; the installer shows the actual API URL.

Windows can reserve the default port `8790` in a Hyper-V/WinNAT excluded range.
In that case setup automatically selects the next free port (`18790`, `28790`,
...), writes `0.0.0.0:<port>` inside WSL, and records the Windows URL in
`%LOCALAPPDATA%\FlashServer\api-url.txt`. The desktop client and the installer's
final health check read that file, so the client, installer, and API docs all use
the same selected port.

New installs use a dedicated WSL distribution named `flashserver_ubuntu` (the
official Ubuntu rootfs is imported under that name). Upgrades keep using an
existing `Ubuntu` distribution when it already contains
`/etc/flashserver/config.json`, so user data is not duplicated or lost. The
selected name is stored in `%LOCALAPPDATA%\FlashServer\distro.txt` and used by
the desktop client and the logon task. WSL has no in-place rename; migrating an
existing `Ubuntu` requires `wsl --export` + `wsl --unregister` + `wsl --import`.

Setup enables domestic mirrors by default (writes `~/.flashcli/mirror.env`) and
adds a Windows firewall rule `FlashServer models` for inbound TCP (Private/
Domain). The firewall port list can be changed from **Settings → WSL 资源 →
防火墙端口**; an empty list means all TCP ports.

The installer's error dialog shows an ASCII-only tail of `setup.log` so
UTF-16/OEM output from `wsl.exe` cannot render as mojibake. The full UTF-8 log
remains in `%LOCALAPPDATA%\FlashServer\logs\setup.log`.

The installer also ships the `flashcli-bundle` Python source. Setup extracts it
to `/usr/local/share/flashcli/flashcli-bundle` and writes
`FLASHCLI_BUNDLE_PIP_SPEC` to `~/.flashcli/install.env`, so creating a bundle
virtualenv does not need `git` or GitHub access from WSL.

For automation/debugging, `flashserver-setup --progress-file FILE` writes the
`[n/8]` lines and a final `DONE <code>` (`0` ready, `3` restart required, `2`
error). The full trace including `wsl.exe`/`schtasks.exe` output is written to
`%LOCALAPPDATA%\FlashServer\logs\setup.log` (WSL/CLI logs remain under
`~/.flashcli/logs`).

### Clean Windows VM check

Use a Windows 10 2004+/Windows 11 x64 VM with internet access and nested
virtualization enabled (VT-x/AMD-V); WSL2 cannot start without it.

1. Confirm the VM is clean: `wsl.exe --status` fails and `wsl.exe -l -v` lists no `flashserver_ubuntu` (or legacy `Ubuntu`).
2. Run `flashserver-setup-windows-amd64-v<version>.exe`. The wizard must show the setup progress
   page with a live log (current step, heartbeat, and rootfs download progress); on a machine
   without WSL2 the first run may stop at step 1 and ask for a restart. The progress page has a
   Cancel button.
3. Restart when asked and run the installer again. It must show steps 1-8 and finish
   with "FlashServer is installed and ready."
4. Verify the environment independently (the installer may have selected a port other than 8790):
   ```powershell
   $distro = (Get-Content "$env:LOCALAPPDATA\FlashServer\distro.txt").Trim()
   wsl.exe -l -v
   wsl.exe -d $distro -u root systemctl is-active flashserver   # active
   $url = (Get-Content "$env:LOCALAPPDATA\FlashServer\api-url.txt").Trim()
   (Invoke-WebRequest -UseBasicParsing "$url/health").StatusCode  # 200
   ```
5. Confirm the desktop client opens, the overview shows the service running, and
   auto-start is enabled. Re-running the installer must succeed without duplicating services.

The CLI remains available for automation:

```powershell
flashserver-setup.exe --backend wsl
```

## Install

Linux:

```bash
sudo flashserver-setup
```

It installs `flashcli`/`flashserver` under `/usr/local/bin`, writes `/etc/flashserver/config.json`, creates `flashserver.service`, enables it at boot, and checks `/health`. Setup prints `[n/N]` step lines and writes the full trace (including `wsl.exe`/`schtasks.exe` output) to `~/.flashcli/logs/setup.log`.

Windows (run from an elevated terminal; the UI installer does this automatically):

```powershell
flashserver-setup.exe
```

It imports the official Ubuntu WSL2 rootfs as the `flashserver_ubuntu` distro
(no custom image; a legacy `Ubuntu` that already holds a FlashServer config is
reused), enables WSL2 itself when missing (`wsl --install --no-distribution`,
with a DISM fallback on older Windows 10), enables systemd in `/etc/wsl.conf`,
installs the Linux binaries inside WSL, registers `flashserver.service`, and
creates the `flashserver-wsl` logon task. A first run on a machine with no WSL2
may require one Windows restart; run setup again afterwards.

**Disk location.** Model weights and bundle runtimes live inside the FlashServer
WSL virtual disk (`ext4.vhdx`). The UI installer defaults it to a sibling of the
installation directory (`<install dir parent>\FlashServerWSL`); when installing
under `Program Files`, it defaults to `%LOCALAPPDATA%\FlashServerWSL` because
WSL may not be able to create a VHDX under that ACL. `--wsl-dir DIR` moves the
distro to another NTFS drive (WSL has no install-time location flag, so setup
installs it and then runs `wsl --manage <distro> --move DIR` while the distro is
stopped). Deleting data later does **not** shrink
the VHDX: clean up with `flashcli du` / `flashcli cache clean` /
`flashcli bundle clean`, then shut WSL down and compact the disk
(`wsl --manage <distro> --set-sparse true`, or `diskpart` compact).

**Restricted networks.** When `wsl --install` cannot reach the Microsoft Store
or GitHub (or hangs for 90 seconds with no progress), setup downloads the
official Ubuntu 24.04 cloud rootfs (Tsinghua and
USTC mirrors first, then `cloud-images.ubuntu.com`) and imports it into the
selected directory with `wsl --import`. `--distro-rootfs FILE` uses a local
rootfs tarball instead (offline installs).

By default setup downloads the matching `flashcli-linux-<arch>` and `flashserver-linux-<arch>` release assets and verifies `sha256sums.txt`. Use `--bin-dir DIR` to consume local release assets instead, or `--release-version` / `--release-base` to pin a release source.

`--backend` defaults to `auto` (`native` on Linux, `wsl` on Windows) and normally does not need to be specified. `--dry-run` prints the platform plan without changing the host. `--no-service` installs binaries and config only; use it in containers or hosts without an active systemd (start `flashserver --config ...` manually).

## Config

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

- `max_loaded=0`: admit by GPU memory only.
- WSL uses `addr=0.0.0.0:8790` by default (setup may choose another port when 8790 is reserved), `public_host=localhost`, `serve_host=0.0.0.0` so Windows can reach the WSL services through localhost forwarding.
- `token` is optional and absent by default. When set, it protects every API path except `/health`, `/`, `/docs`, `/ui/*`, and `/openapi.yaml`; send `Authorization: Bearer <token>` or `X-Flashcli-Token`.

## API

```text
GET  /health
GET  /v1/version
GET  /v1/models                 cached models + loaded instances + serve capability
GET  /v1/models/loaded
GET  /v1/storage                unique allocated bytes per area (hardlinks counted once)
GET  /v1/mirror                 domestic mirror state and endpoints
POST /v1/mirror                 enable/disable domestic mirrors for new downloads
GET  /v1/resources              GPU, loaded models, slot counts
GET  /v1/system                 OS/WSL/GPU/driver/CUDA/SM/torch/CPU/RAM/uptime
GET  /v1/logs                   ?kind=server|model&ref=...&lines=N&since=unix
GET  /v1/logs/download          full daemon/model log attachment
GET  /v1/gpu                    devices + CUDA processes
GET  /v1/gpu/history            ?seconds=N recent GPU+CPU telemetry samples
GET  /v1/system/history         alias of /v1/gpu/history
GET  /v1/ws                     WebSocket: system/models/storage/mirror snapshots + job progress
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/jobs/{id}/cancel        cancel a running job (smoke/download/load)
POST /v1/models/load            {"ref":"...","async":true} → job_id (or endpoint/pid/state)
POST /v1/models/unload          {"ref":"..."}
GET  /v1/models/options         ?ref=... manifest serve_options + saved host/port/values
PUT  /v1/models/options         {"ref":"...","host":"0.0.0.0","port":0,"options":{...}}
DELETE /v1/models/options       ?ref=... reset to bundle/server defaults
POST /v1/models/smoke           {"ref":"..."} run-only smoke test or started-serve request test
POST /v1/models/clean           {"refs":[...]} remove local bundle/weight caches
POST /v1/storage/clean          {"targets":["cache"]} remove shared cache (not model data)
GET  /v1/catalog                ?q=&tag=&sort=updated|downloads&page=&page_size=
GET  /v1/catalog/tags
GET  /v1/catalog/{id}           repository detail + versions
POST /v1/ui/chat                local console helper: {"ref":"...","body":{...}}
GET  /docs                      HTML API reference
GET  /openapi.yaml              OpenAPI 3.1 contract
GET  /                          embedded local console
```

`/v1/models/clean` removes model-related cache per ref: the bundle, its runtime, and weights when no other cached ref uses them. Shared weights/runtime are reference-counted by the remaining bundle markers and are kept. `/v1/storage/clean` removes only the **shared cache** (download cache, base Python, uv); it never touches bundle/weight/runtime data. Both return freed bytes.

Disk accounting and cleanup path selection live in the shared `host` package: `flashcli du` uses the same unique-allocation accounting as `/v1/storage`, `flashcli models list` uses the same model data as `/v1/models`, and `flashcli bundle clean` uses the same ref-path resolver as `/v1/models/clean`.

Cleanup responsibilities:

- **Shared cache** — `~/.flashcli/cache` (downloads/uv/FlashHub index), `~/.flashcli/python` (base interpreter), `~/.flashcli/tools` (uv). Re-downloadable; no model data.
  - CLI: `flashcli cache clean`
  - API: `POST /v1/storage/clean {"targets":["cache"]}`
- **Model data** — bundle, weights (shared by `source/repo@revision`), and the per-bundle runtime.
  - CLI: `flashcli bundle clean <ref> --all` (one ref), `flashcli bundle clean` (all runtimes), `flashcli bundle clean --all` (all bundles/weights/runtimes)
  - API: `POST /v1/models/clean {"refs":[...]}`
  - Shared weights/runtime are kept while another cached ref still references them; removing one ref only drops its marker/reference.
- Desktop Settings → 清理缓存 cleans the shared cache only. Model-related cleanup is in the Models page (multi-select cleanup), which maps to `/v1/models/clean`.

Legacy API targets `python` and `tools` are still accepted as cache sub-areas; `runtimes` is rejected (use model cleanup).

The authoritative request/response schema is [openapi.yaml](openapi.yaml) (also served at `/openapi.yaml`).

There is intentionally no `/v1/infer` endpoint. After `load`, call the returned `endpoint` directly.

```bash
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

Add `-H "X-Flashcli-Token: $TOKEN"` only when a token is configured.

`load` requires a bundle with a `serve` entry (checked in top-level `entry`, `defaults.entry`, and per-environment entries). Run-only bundles (VLA policies and similar) are rejected before a serve process is started with `bundle "..." is run-only (no serve entry)`; use `flashcli run <ref>` for those. The desktop client's FlashHub page downloads versions only; the Local tab shows "仅 run" when the bundle has no serve entry and hides the load action.

`POST /v1/models/smoke` starts an async smoke job for a ready model. Run-only bundles execute `flashcli run <ref>` at low CPU priority (`nice -n 10`) with manifest defaults (bundles that require external files such as images report that in the log); a started serve bundle receives one OpenAI-compatible chat request (`ping`). The desktop asks for confirmation before a run smoke test; output/progress stream as a `smoke` job over `/v1/ws` and are appended to `<ref>.smoke.log`. Closing or cancelling the dialog, or quitting the client, cancels the job (`POST /v1/jobs/{id}/cancel`); the server also stops the job when its timeout expires. The serve test requires the model to be started first.

## Startup parameters and WSL resources

A bundle's `serve_options` (from `flashcli-bundle.json`, including v4
environment overlays) is the source for per-model startup parameters. The
desktop's **Models → model detail → 参数** dialog renders these fields together
with a host and port:

- `host`: `0.0.0.0` binds all interfaces, `127.0.0.1` is local-only.
- `port`: `0` uses any free port; a fixed port is allowed and checked for
  conflicts. Host-level `host`/`ip`/`port` entries in `serve_options` are
  represented by the host/port fields and are not added twice.
- Option values: empty means the bundle default; non-empty values are appended
  as `--flag value` to `flashcli serve`.
- Settings are stored server-side in
  `$FLASHCLI_HOME/flashserver/serve-options.json`, so the CLI/API and desktop
  see the same values. Saving while a model is loaded requires unload + start.

Windows localhost forwarding makes `host=0.0.0.0` reachable at
`http://localhost:<port>` on the Windows host. LAN/public access additionally
requires WSL mirrored networking and a firewall rule:

1. Desktop **Settings → WSL 资源 → 局域网访问（WSL 镜像网络）** writes
   `[wsl2] networkingMode=mirrored` to `%USERPROFILE%\.wslconfig`.
2. The client asks for UAC and allows the configured inbound TCP ports
   (default: all TCP ports; e.g. `18000-18999`) for the Private/Domain
   profiles.
3. Applying WSL settings restarts WSL (`wsl --shutdown`) and starts
   `flashserver` again; running models are interrupted.

The firewall rule uses the Private/Domain profiles. Access from the public
internet additionally needs a Public profile rule and router port forwarding;
do not expose the model API without authentication.

The same panel edits `memory`, `processors`, and `swap` in `.wslconfig`.
Empty values use WSL defaults (memory 50% of Windows RAM, all logical CPUs,
swap 25% of memory). These settings apply to every WSL2 distro and require a
WSL restart. Mirrored networking requires Windows 11 22H2+ and a recent WSL.

## Inspecting startup parameters inside WSL

Enter the distro and inspect the actual child process:

```bash
wsl -d flashserver_ubuntu
ps -ef | grep '[f]lashcli.*serve'
# /proc/<pid>/cmdline separates arguments with NUL
cat /proc/<pid>/cmdline | tr '\0' ' '; echo
ss -lntp | grep <port>
cat /root/.flashcli/flashserver/serve-options.json
journalctl -u flashserver -n 100 --no-pager
```

The service runs as root, so its `FLASHCLI_HOME` is normally
`/root/.flashcli`. If a different `--home` was used, read `Environment=` from
`/etc/systemd/system/flashserver.service`. Legacy installs use `Ubuntu`; read
`%LOCALAPPDATA%\FlashServer\distro.txt` for the active name. From Windows, the
same checks work without an interactive shell:

```powershell
wsl -d flashserver_ubuntu -- ps -ef
wsl -d flashserver_ubuntu -- ss -lntp
```

## Timing expectations

Reference measurements on a Windows 11 host with an existing WSL2 Ubuntu, RTX 4060 8 GB, and a ~100 Mbit/s link. First-run preparation dominates; repeat runs hit the cache.

| Phase | Warm / cached | First time |
|---|---|---|
| UI installer + setup (`[1/8]`…`[8/8]`) | 4–6 s | WSL2/Ubuntu missing: +5–15 min and usually one reboot |
| Bundle sync (FlashHub) | ~0 | ~46 s for 181 MiB at ~4.7 MB/s |
| Weights (ModelScope/HF) | ~0 | ~6–7 min for ~7 GiB at ~19 MB/s |
| Python 3.12 + venv + torch/deps | ~0 | ~2–5 min (network/cache dependent) |
| Model load + autotune (pi05) | ~40 s | same, after preparation |
| Single inference (pi05, 10×7 actions) | ~3.3–3.6 s | — |
| Smoke model load via `/v1/models/load` | ~2.5 s | — |

Repeat install + smoke load is roughly 8 s; install + first pi05 inference is roughly 10–15 min. These scale with bundle/weight size and download speed.

## Resource admission

`load` is rejected with `409 RESOURCE_EXHAUSTED` when:

- `max_loaded > 0` and the resident/pending count reaches it; or
- the selected bundle declares `resources.min_vram_mib` and free VRAM minus `min_free_vram_mib` is insufficient.

Bundles should declare measured VRAM:

```json
"resources": {
  "min_vram_mib": 12288
}
```

A v4 environment overlay may override it. Bundles without the field are admitted only by the slot limit.

## Service lifecycle

`flashserver` starts `flashcli serve <ref> --host <serve_host> --port <allocated>` on load and stops that child on unload/shutdown. It waits for `/health` before reporting `ready`.

Linux uses a system-level systemd service. WSL enables systemd and uses a Windows `ONLOGON` task that starts the distro and keeps it alive with a hidden `sleep infinity` session; WSL's `vmIdleTimeout` otherwise stops the distro (and the resident service) about a minute after the last session exits. No custom WSL image is used in this phase.

Service control without uninstalling:

```powershell
flashserver-setup.exe --stop-service        # stop daemon, disable auto-start (admin)
flashserver-setup.exe --disable-autostart  # disable auto-start, keep daemon running (admin)
flashserver-setup.exe --enable-autostart   # enable auto-start, keep current run state (admin)
flashserver-setup.exe --start-service      # enable auto-start, start daemon (admin)
```

The desktop client exposes the same actions; stopping/starting the daemon itself does not need elevation, only the auto-start change does. The current auto-start state is reported by `/v1/system` (`enabled`, `disabled` or `unknown`).

## Uninstall

```bash
sudo flashserver-setup --uninstall
```

Removes the service, config, and `flashserver` binary. Keeps `FLASHCLI_HOME` (bundles, weights, runtimes, caches), the WSL distro, and the desktop settings.

Optional cleanup flags:

| Flag | Removes |
|---|---|
| `--purge-models` | `FLASHCLI_HOME` (bundles, weights, runtimes, caches) and the extracted `flashcli-bundle` source |
| `--remove-cli` | `/usr/local/bin/flashcli` |
| `--purge-settings` | desktop client settings and the Windows setup log (`%LOCALAPPDATA%\FlashServer`) |
| `--purge-distro` | the active FlashServer WSL distro (`distro.txt`; `flashserver_ubuntu` or legacy `Ubuntu`) and its `ext4.vhdx` (frees the whole virtual disk; all data inside is lost; WSL only) |

The Windows UI uninstaller shows a select-all option plus model-cache, CLI, client-settings, and distro checkboxes before removing files; a silent uninstall keeps everything. Uninstalling while a model is loading or starting stops the service and its jobs first (load/download state resumes from the cache on the next install).
