# flashserver: install and operations

<p align="right"><strong>English</strong> · <a href="flashserver-install.zh-CN.md">简体中文</a></p>

How to install, configure, run, and remove the resident scheduler. Start with
[flashserver.md](flashserver.md) for the overview.

## Install

### Windows installer

Use `flashserver-setup-windows-amd64-v<version>.exe` (elevated). It drives
`flashserver-setup` behind a live progress page and then opens the desktop
client:

```text
[1/8] check/enable WSL2  → [2/8] register the distro → [3/8] enable systemd
[4/8] install Linux payload → [5/8] config + unit → [6/8] start service
[7/8] logon task + firewall rule → [8/8] wait for /health
```

- Exit code **3** means Windows must restart; run the installer again afterwards.
  Re-running is idempotent and repairs the install without duplicating services.
- If Windows reserves `8790` (Hyper-V/WinNAT), setup picks the next free port and
  records the URL in `%LOCALAPPDATA%\FlashServer\api-url.txt`; the client,
  installer, and API docs read that file.
- New installs import the distro as `flashserver_ubuntu`; an existing `Ubuntu`
  that already has `/etc/flashserver/config.json` is reused. The active name is
  in `%LOCALAPPDATA%\FlashServer\distro.txt`.
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
| `--uninstall` / `--purge-*` | See [Uninstall](#uninstall) |

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

- `max_loaded=0` admits by GPU memory only. A bundle's `resources.min_vram_mib`
  must fit free VRAM minus `min_free_vram_mib`, otherwise `load` returns
  `409 RESOURCE_EXHAUSTED`; the slot limit also counts starting models.
- WSL defaults: `addr=0.0.0.0:8790`, `public_host=localhost`,
  `serve_host=0.0.0.0` (Windows reaches the service through localhost forwarding).
- `token` is optional. When set, every path except `/health`, `/`, `/docs`,
  `/ui/*`, and `/openapi.yaml` requires `Authorization: Bearer <token>` or
  `X-Flashcli-Token`.
- Mirrors: `POST /v1/mirror {"enabled":true}` (or the desktop toggle) writes
  `~/.flashcli/mirror.env` (Aliyun pip, hf-mirror, gh-proxy, Gitee, SJTU torch)
  and applies to new downloads without restarting the service.

## Service lifecycle

On load, `flashserver` starts
`flashcli serve <ref> --host <serve_host> --port <allocated>` and waits for
`/health` before reporting `ready`; unload/shutdown stops the child.

Linux uses a systemd unit. WSL uses systemd plus the `flashserver-wsl` logon task,
which starts the distro and keeps it alive with a hidden `sleep infinity` session
(otherwise WSL stops the idle distro after about a minute).

```powershell
flashserver-setup.exe --stop-service        # stop service, disable auto-start
flashserver-setup.exe --disable-autostart   # keep running, disable auto-start
flashserver-setup.exe --enable-autostart    # enable auto-start, keep state
flashserver-setup.exe --start-service       # enable auto-start and start
```

Service state and auto-start are independent: stopping never disables auto-start,
and toggling auto-start never starts or stops the service. `/v1/system` reports
the current auto-start state (`enabled`, `disabled`, `unknown`).

## Uninstall

```bash
sudo flashserver-setup --uninstall          # keeps model caches and the distro
```

| Flag | Removes |
|---|---|
| `--purge-models` | `FLASHCLI_HOME` (bundles, weights, runtimes, caches) and the extracted `flashcli-bundle` |
| `--remove-cli` | `/usr/local/bin/flashcli` |
| `--purge-settings` | desktop settings and the installer log (`%LOCALAPPDATA%\FlashServer`) |
| `--purge-distro` | the active WSL distro and its `ext4.vhdx` (all data inside; WSL only) |

The Windows uninstaller offers the same four cleanups plus select-all; a silent
uninstall keeps everything. Uninstalling during load/start stops the service and
its jobs first (cached state resumes on the next install).

## Storage and networks

- **Disk location**: weights and runtimes live in the WSL `ext4.vhdx`, defaulting
  to a sibling of the install directory (`%LOCALAPPDATA%\FlashServerWSL` under
  `Program Files`). Deleting data does not shrink it: clean with `flashcli du` /
  `flashcli cache clean` / `flashcli bundle clean`, then compact with
  `wsl --manage <distro> --set-sparse true` or `diskpart`.
- **Restricted networks**: when `wsl --install` cannot reach the Store/GitHub (or
  makes no progress for 90 seconds), setup imports the official Ubuntu 24.04
  rootfs from Tsinghua/USTC mirrors (then `cloud-images.ubuntu.com`); use
  `--distro-rootfs FILE` for offline installs.
- **Ports**: the daemon is local-only by default. LAN/public access needs mirrored
  networking and firewall ports — see
  [flashserver-desktop.md](flashserver-desktop.md#startup-parameters-and-lan-access).

## Troubleshooting

Inspect the running process inside WSL:

```bash
wsl -d flashserver_ubuntu
ps -ef | grep '[f]lashcli.*serve'
cat /proc/<pid>/cmdline | tr '\0' ' '; echo   # NUL-separated args
cat /root/.flashcli/flashserver/serve-options.json
journalctl -u flashserver -n 100 --no-pager
```

The service runs as root (`FLASHCLI_HOME=/root/.flashcli` unless `--home` was
used); the active distro name is in `%LOCALAPPDATA%\FlashServer\distro.txt`.
Setup and daemon logs: `%LOCALAPPDATA%\FlashServer\logs\setup.log` on Windows,
`~/.flashcli/logs` inside the distro.

Typical timings (RTX 4060 8 GB, ~100 Mbit/s): installer 4–6 s warm (5–15 min and
one reboot when WSL2 is missing); bundle sync ~46 s per 181 MiB; weights ~6–7 min
per ~7 GiB; Python + torch 2–5 min; model load ~40 s.
