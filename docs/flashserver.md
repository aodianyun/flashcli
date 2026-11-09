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

Open `http://localhost:8790/` after installation. The embedded console shows GPU/VRAM, utilization, temperature, clocks, power (when the driver exposes it), CUDA/SM/torch environment, CUDA process memory (native Linux; WSL usually does not expose it), CPU model/cores/load/per-core utilization, RAM/swap, 5-minute GPU and CPU charts, service uptime, cached models, loaded models, logs, and can load/unload models and test chat. It is served by the same binary (no extra assets or Node build). The HTTP contract is published at `/openapi.yaml` and mirrored in [openapi.yaml](openapi.yaml).

## Windows UI installer

Windows users should use the UI installer rather than the CLI:

```text
FlashServer-Setup-<version>.exe
```

It runs elevated, checks/installs WSL2 Ubuntu, installs the Linux payload,
starts `flashserver.service`, creates the Windows logon task, and verifies
the daemon. On success it opens `http://localhost:8790/` (the local console).
If Windows requires a reboot to enable WSL2, run the installer again after
reboot; the setup engine is idempotent.

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

Windows:

```powershell
flashserver-setup.exe
```

It uses the official Ubuntu WSL2 distribution (no custom image), enables systemd in `/etc/wsl.conf`, installs the Linux binaries inside WSL, registers `flashserver.service`, and creates the `flashserver-wsl` logon task.

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
- WSL uses `addr=0.0.0.0:8790`, `public_host=localhost`, `serve_host=0.0.0.0` so Windows can reach the WSL services through localhost forwarding.
- `token` is optional and absent by default. When set, it protects every API path except `/health`, `/`, `/ui/*`, and `/openapi.yaml`; send `Authorization: Bearer <token>` or `X-Flashcli-Token`.

## API

```text
GET  /health
GET  /v1/version
GET  /v1/models                 cached models + loaded instances
GET  /v1/models/loaded
GET  /v1/storage
GET  /v1/resources              GPU, loaded models, slot counts
GET  /v1/system                 OS/WSL/GPU/driver/CUDA/SM/torch/CPU/RAM/uptime
GET  /v1/logs                   ?kind=server|model&ref=...&lines=N
GET  /v1/gpu                    devices + CUDA processes
GET  /v1/gpu/history            ?seconds=N recent GPU+CPU telemetry samples
GET  /v1/system/history         alias of /v1/gpu/history
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/models/load            {"ref":"...","async":true} → job_id (or endpoint/pid/state)
POST /v1/models/unload          {"ref":"..."}
POST /v1/ui/chat                local console helper: {"ref":"...","body":{...}}
GET  /openapi.yaml              OpenAPI 3.1 contract
GET  /                          embedded local console
```

The authoritative request/response schema is [openapi.yaml](openapi.yaml) (also served at `/openapi.yaml`).

There is intentionally no `/v1/infer` endpoint. After `load`, call the returned `endpoint` directly.

```bash
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

Add `-H "X-Flashcli-Token: $TOKEN"` only when a token is configured.

`load` requires a bundle with a `serve` entry. Run-only bundles (VLA policies and similar) are rejected immediately with the bundle's own error, for example `bundle "pi05_libero" does not support serve`; use `flashcli run <ref>` for those.

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

## Uninstall

```bash
sudo flashserver-setup --uninstall
```

Removes the service, config, and flashserver binary. Keeps `FLASHCLI_HOME`, bundles, and model weights. Windows uninstall is wired through the UI installer; WSL distro and model caches are kept.
