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

The Windows installer ships `FlashServer.exe`, a Rust + egui/eframe desktop client (no WebView, no console window): overview (card layout with GPU/CPU environment and 0-100 charts, compact two-row service/disk cards, flat GPU/VRAM/CPU/RAM status bar), models (local cache plus on-demand FlashHub search/categories/versions, separate Bundle/runtime/weight sizes, ready and started states, async load/start progress, row actions for info/model logs/use/start/stop, and multi-select cache cleanup), logs (`journalctl` tail or per-model serve logs with clear and native Save-As), and settings (service start/stop, auto-start, domestic-mirror toggle, shared-cache cleanup with per-item sizes, theme, API docs). It talks to the daemon over WebSocket (`/v1/ws`) with HTTP polling as fallback. Load progress (bundle sync, Python runtime/venv, weights) and start progress (serve process/health) show the bundle ref, phase, file/byte counts and percentage; downloads retry on checksum mismatch. Downloads are serialized: the client disables load/download/start actions while a job is active, and a concurrent `/v1/pull` returns HTTP 409. "加载" prepares the bundle, Python runtime/venv and weights to a ready state; only a ready model can be started with "启动", and "停止" ends its serve process. Model size is Bundle + per-model runtime + weights; weights are stored by `source/repo@revision` and may be shared across bundle versions (the total de-dupes by weights key), while each bundle/version has its own runtime directory. Python/tools/download caches are shared storage areas listed in Settings; runtime directories can also be bulk-cleaned there, or removed with the model.

- Source: `desktop/`; build with `cargo build --release` (Rust MSVC toolchain; put `cargo` on PATH). Output: `desktop/target/release/FlashServer.exe` (~4.7 MB).
- Memory: ~110-125 MB working set (GPU context + CJK font + egui stores).
- Theme: dark by default, switched in Settings or with `Ctrl+T`; saved to `%LOCALAPPDATA%\FlashServer\settings.json`.
- Domestic mirrors: Settings → 下载源 enables pip (Aliyun), HuggingFace (`hf-mirror.com`), GitHub (`gh-proxy.com`) and the Gitee `flashcli` repo. It writes `~/.flashcli/mirror.env` and applies to new downloads immediately; apt sources are not changed.
- Destructive actions (stop service, disable auto-start, stop model, quit) ask for confirmation.
- Service buttons use `wsl.exe` (no UAC). The auto-start toggle calls `flashserver-setup --enable-autostart/--disable-autostart` and therefore prompts for UAC; it does not start or stop the service.
- Service state and auto-start are independent: stopping never disables auto-start, starting never enables it, and auto-start changes never start/stop the service. Long operations show a modal progress overlay and a result toast.
- API docs open the configured API URL + `/docs` (the client reads the port from `%LOCALAPPDATA%\FlashServer\api-url.txt`).
- The code compiles cross-platform; service control is wired for Windows/WSL first, Linux uses `systemctl` (best effort) and macOS has no flashserver backend yet.

## Domestic mirrors

Settings → 下载源 (or `POST /v1/mirror {"enabled":true}`) enables China-friendly endpoints for bundle preparation and weight downloads:

- pip: `https://mirrors.aliyun.com/pypi/simple/`
- HuggingFace: `https://hf-mirror.com`
- GitHub: `https://gh-proxy.com/`
- FlashCLI source fallback: `https://gitee.com/aodiansoft/flashcli.git`
- PyTorch wheels: SJTU mirror (`mirror.TorchIndexURL`)

The toggle writes `~/.flashcli/mirror.env` and applies to new downloads without restarting the service. `GET /v1/mirror` returns the current state. This is the same endpoint set as `install.sh --mirror`; it does not rewrite apt sources. The desktop setting is disabled while the service is stopped or a download/load/start job is running.

## Windows UI installer

Windows users should use the UI installer rather than the CLI:

```text
FlashServer-Setup-<version>.exe
```

It runs elevated and drives `flashserver-setup` behind a live progress page
(`Step N of 8`, with the current phase) instead of a silent wait:

```text
UI installer (admin)
  → extract payload to %ProgramFiles%\FlashServer\payload
  → [1/8] check WSL2; enable it with `wsl --install --no-distribution` when missing
  → [2/8] install/register Ubuntu (DISM fallback for older Windows 10)
  → [3/8] enable systemd  → [4/8] install Linux payload
  → [5/8] write config + unit → [6/8] start service
  → [7/8] create the Windows logon task → [8/8] wait for /health
  → re-check `systemctl is-active flashserver` and /health
  → launch the desktop client
```

If enabling WSL2 requires a Windows restart, setup exits with code **3**. The
installer explains that a restart is required, keeps the client closed, and the
finished page asks you to run Setup again after restarting. The second run is
idempotent and completes the Ubuntu/service installation. On success the
finished page means the environment was verified ready, not just that files were
copied; the installer shows the actual API URL.

Windows can reserve the default port `8790` in a Hyper-V/WinNAT excluded range.
In that case setup automatically selects the next free port (`18790`, `28790`,
...), writes `0.0.0.0:<port>` inside WSL, and records the Windows URL in
`%LOCALAPPDATA%\FlashServer\api-url.txt`. The desktop client and the installer's
final health check read that file, so the client, installer, and API docs all use
the same selected port.

The installer also ships the `flashcli-bundle` Python source. Setup extracts it
to `/usr/local/share/flashcli/flashcli-bundle` and writes
`FLASHCLI_BUNDLE_PIP_SPEC` to `~/.flashcli/install.env`, so creating a bundle
virtualenv does not need `git` or GitHub access from WSL.

For automation/debugging, `flashserver-setup --progress-file FILE` writes the
`[n/8]` lines and a final `DONE <code>` (`0` ready, `3` restart required, `2`
error). The full trace including `wsl.exe`/`schtasks.exe` output is written to
`%USERPROFILE%\.flashcli\logs\setup.log`.

### Clean Windows VM check

Use a Windows 10 2004+/Windows 11 x64 VM with internet access and nested
virtualization enabled (VT-x/AMD-V); WSL2 cannot start without it.

1. Confirm the VM is clean: `wsl.exe --status` fails and `wsl.exe -l -v` lists no Ubuntu.
2. Run `FlashServer-Setup-<version>.exe`. The wizard must show the setup progress
   page; on a machine without WSL2 the first run may stop at step 1 and ask for a restart.
3. Restart when asked and run the installer again. It must show steps 1-8 and finish
   with "FlashServer is installed and ready."
4. Verify the environment independently (the installer may have selected a port other than 8790):
   ```powershell
   wsl.exe -l -v
   wsl.exe -d Ubuntu -u root systemctl is-active flashserver   # active
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

It uses the official Ubuntu WSL2 distribution (no custom image), enables WSL2
itself when missing (`wsl --install --no-distribution`, with a DISM fallback on
older Windows 10), enables systemd in `/etc/wsl.conf`, installs the Linux
binaries inside WSL, registers `flashserver.service`, and creates the
`flashserver-wsl` logon task. A first run on a machine with no WSL2 may require
one Windows restart; run setup again afterwards.

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
GET  /v1/ws                     WebSocket: 1 Hz system snapshots + job progress
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/models/load            {"ref":"...","async":true} → job_id (or endpoint/pid/state)
POST /v1/models/unload          {"ref":"..."}
POST /v1/models/clean           {"refs":[...]} remove local bundle/weight caches
POST /v1/storage/clean          {"targets":["cache","python","tools","runtimes"]}
GET  /v1/catalog                ?q=&tag=&sort=updated|downloads&page=&page_size=
GET  /v1/catalog/tags
GET  /v1/catalog/{id}           repository detail + versions
POST /v1/ui/chat                local console helper: {"ref":"...","body":{...}}
GET  /docs                      HTML API reference
GET  /openapi.yaml              OpenAPI 3.1 contract
GET  /                          embedded local console
```

`/v1/models/clean` refuses loaded/in-flight refs and keeps weights shared with another cached ref. `/v1/storage/clean` refuses `runtimes` while models are resident/loading; both return freed bytes.

Disk accounting and cleanup path selection live in the shared `host` package: `flashcli du` uses the same unique-allocation accounting as `/v1/storage`, `flashcli models list` uses the same model data as `/v1/models`, and `flashcli bundle clean` uses the same ref-path resolver as `/v1/models/clean`.

Cleanup scopes are intentionally different:

- `flashcli cache clean --all` removes **package caches only**: `UV_CACHE_DIR`, `~/.flashcli/tools/uv`, and `~/.flashcli/cache/repo-index`.
- `flashcli cache clean --storage` removes **whole storage areas** (`cache`, `python`, `tools`, `runtimes`), matching `/v1/storage/clean` with all targets. Stop resident models first.
- `flashcli cache clean --target cache|python|tools|runtimes` removes one shared area; `/v1/storage/clean` accepts the same four area names.
- Desktop Settings → 清理缓存 maps directly: 下载缓存 = `--target cache`, Python 运行时 = `--target python`, 工具 = `--target tools`, 模型运行时（全部） = `--target runtimes`.
- Bundle/weights/per-model runtime cleanup uses `/v1/models/clean` or `flashcli bundle clean`; neither cache command touches them.

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

Removes the service, config, and flashserver binary. Keeps `FLASHCLI_HOME`, bundles, and model weights. Windows uninstall is wired through the UI installer; WSL distro and model caches are kept.
