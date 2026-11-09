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
- No remote mode. No inference proxy: `flashserver` returns each model's endpoint.
- `flashserver` must run as a boot-started service. It schedules multiple models when GPU memory and the configured slot limit allow it.

## Windows UI installer

Windows users should use the UI installer rather than the CLI:

```text
FlashServer-Setup-<version>.exe
```

It runs elevated, checks/installs WSL2 Ubuntu, installs the Linux payload,
starts `flashserver.service`, creates the Windows logon task, and verifies
`http://localhost:8790/health`. If Windows requires a reboot to enable WSL2,
the installer should be run again after reboot; the setup engine is idempotent.

The CLI remains available for automation:

```powershell
flashserver-setup.exe --backend wsl
```

## Install

Linux:

```bash
sudo flashserver-setup
```

It installs `flashcli`/`flashserver` under `/usr/local/bin`, writes `/etc/flashserver/config.json`, creates `flashserver.service`, enables it at boot, and checks `/health`.

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
  "token": "local-secret",
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
- `token` protects every API path except `/health`; send `Authorization: Bearer <token>` or `X-Flashcli-Token`.

## API

```text
GET  /health
GET  /v1/version
GET  /v1/models                 cached models + loaded instances
GET  /v1/models/loaded
GET  /v1/storage
GET  /v1/resources              GPU, loaded models, slot counts
GET  /v1/gpu
POST /v1/pull
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/events
POST /v1/models/load            {"ref":"..."} → endpoint/pid/state
POST /v1/models/unload          {"ref":"..."}
```

There is intentionally no `/v1/infer` endpoint. After `load`, call the returned `endpoint` directly.

```bash
curl -H "X-Flashcli-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

`load` requires a bundle with a `serve` entry. Run-only bundles (VLA policies and similar) are rejected immediately with the bundle's own error, for example `bundle "pi05_libero" does not support serve`; use `flashcli run <ref>` for those.

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
