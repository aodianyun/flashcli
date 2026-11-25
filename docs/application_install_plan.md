# FlashHub application install plan

<p align="right"><strong>English</strong> · <a href="application_install_plan.zh-CN.md">简体中文</a></p>

> **Status: implemented (v1).** The manifest schema is specified in
> [app_manifest_standard.md](app_manifest_standard.md) (v1, matching FlashHub).

## Goals

One command installs an application, prepares its models, and leaves them ready:

```bash
flashcli app install xym/workbuddy
```

`flashcli` must work **without** a running `flashserver`; the daemon and the CLI
share one Go implementation (`internal/apps`), and the desktop talks to the
daemon over HTTP only.

## Terminology

| Term | Meaning |
|---|---|
| **Application** | An external app published on FlashHub (`xym/workbuddy`) |
| **App key** | `[namespace/]name[:version]` |
| **Manifest** | `flashcli-application` document (see the manifest standard) |
| **Model bundle** | Existing `flashcli-bundle/<name>:<version>` runtime |
| **Resident daemon** | `flashserver` (unchanged: scheduler, console, API) |

## Responsibilities

| Component | Owns |
|---|---|
| FlashHub | App registry, versions, manifest validation, metadata |
| `internal/apps` (shared) | Manifest use, install policy, app state, model preparation and lifecycle |
| `internal/modelrun` (shared) | Supervising `flashcli serve` children (ports, health, logs, stop) |
| `flashcli` CLI | User interaction, confirmations, exit codes, JSON output |
| `flashserver` | HTTP API used by the desktop; calls the same shared package |
| `flashcli-desktop` | UI only; HTTP/WS to `flashserver` |

No HTTP call from the CLI to the daemon is required (or used) for app operations.

## App key

`xym/workbuddy` resolves the latest version; `xym/workbuddy:1.0.0` pins it.
`flashcli app install` records the resolved version.

## Manifest

`GET /api/v1/apps/{namespace}/{name}[:version]` returns the manifest. The host
validates `format`, `app_format_version`, `protocol_version`, required fields,
and that `name`/`version` match the key. See
[app_manifest_standard.md](app_manifest_standard.md).

## Install flow

Install and start are **separate operations**. Install resolves and validates the
manifest, installs the application itself, and prepares the model bundles. It
never starts a model and never runs setup scripts. Starting is an explicit
action (desktop 启动 / `flashcli app start`).

```text
RESOLVE → VALIDATE → PLATFORM → PREFLIGHT → PLAN
  → CONFIRM_INSTALL (shell command or installer download; page URL: manual)
  → INSTALL_APP (script: run | installer URL: download + run | page: open/copy)
  → PREPARE_MODELS (every default bundle, serial)
  → PREPARED (cached; nothing running)
```

```mermaid
sequenceDiagram
  autonumber
  participant U as User
  participant CLI as CLI / desktop
  participant A as internal/apps
  participant FH as FlashHub
  participant H as internal/host
  participant REG as apps.json (locked)

  U->>CLI: app install xym/workbuddy [--yes] [--dry-run]
  CLI->>A: Install(ref, opts)
  A->>FH: GET /api/v1/apps/xym/workbuddy
  FH-->>A: manifest v1
  A->>A: validate + platform (client OS) + preflight
  alt unsupported or invalid
    A-->>CLI: error (nothing changed)
  end
  alt install command is a page URL
    CLI-->>U: show link (manual install)
    A->>REG: install=skipped(manual)
  else installer URL (.exe/.msi/.dmg/.pkg)
    CLI->>U: show link, ask to download + run
    U-->>CLI: confirmed
    CLI->>CLI: download, run the installer (client OS)
    CLI->>A: install_command=client
    A->>REG: install=executed
  else shell command
    CLI->>U: show command, ask [y/N]
    Note over CLI: non-interactive without -y: skip and record
    U-->>CLI: yes
    CLI->>CLI: execute (powershell -Command / sh -c)
    CLI->>A: install_command=client
    A->>REG: install=executed
  end
  Note over A,H: the application install must finish before this point
  loop every default bundle (serial)
    A->>H: prepare = pull tree + venv + weights
    H-->>A: progress
    A->>REG: bundle=prepared
  end
  A->>REG: state=PREPARED (no connection, no pid/endpoint)
  A-->>CLI: prepared models / state dir
```

### Start flow (separate action)

```text
START → START_MODELS (one group, auto ports) → HEALTH
  → READY + connection → SETUP_SCRIPTS (confirmed, manifest order)
```

A start/health failure rolls back the models started by that run. Setup scripts
run only after `READY`, because they need `{base_url}`/`{model}`/`{api_key}`; a
setup failure is logged and leaves the app `READY` (it does not roll back the
models). A reinstall stops the app's running models first, keeps caches, and
leaves the new set `PREPARED`.

### State machine

```mermaid
stateDiagram-v2
  [*] --> RESOLVING
  RESOLVING --> PLANNED: manifest valid, platform supported
  RESOLVING --> FAILED: invalid manifest or unsupported platform
  PLANNED --> INSTALLING: confirmed script or installer download
  PLANNED --> PREPARING: skipped script or manual page URL
  INSTALLING --> PREPARING: command succeeded
  INSTALLING --> FAILED: command failed (abort)
  PREPARING --> PREPARED: all default bundles prepared
  PREPARING --> FAILED: a bundle failed (abort)
  PREPARED --> STARTING: group start
  STARTING --> READY: all models healthy
  STARTING --> FAILED: any failure (roll back started models)
  READY --> STOPPED: app stop
  READY --> STOPPED: status finds no healthy model (crash; a daemon restart restores first)
  READY --> FAILED: some models are not running
  STOPPED --> READY: app start
  READY --> [*]: app uninstall
```

`status` reconciles the stored state with live health: a `ready` app whose
model process is gone is reported as `stopped` (so 启动 is enabled and the dead
endpoint is not advertised), and the connection URL is recomputed after every
start because the scheduler picks the port. Start/stop are also available as
async jobs (`?async=1`) so clients can stream their progress lines instead of
showing a silent spinner while a model loads.

On daemon start, an interrupted transition is normalized instead of staying
stuck: `starting` is retried (a start canceled by the shutdown keeps its
intent), `installing`/`preparing` becomes `failed` with a reinstall hint, and
`stopping` is completed as `stopped`. Install/start/stop are serialized per
application, so a restore and a manual click cannot start two models and leave
the connection or the setup config pointing at different ports.

### Setup scripts (optional)

After the models become ready, the host runs the manifest's `setup.scripts` in
manifest order for the keys the user confirmed **for this run**. The client (the
desktop dialog on a start, or the CLI prompt per script) is the confirmation
point. Each script is downloaded, verified against `sha256`, and
executed with the explicit argv template (`{base_url}`, `{model}`, `{api_key}`).
A failure is written to the app job log and stops the remaining scripts; the
running app is not marked failed. Apps without `setup.scripts` skip this step.
The confirmed script definitions, keys, and client home are persisted; after a
daemon restart the restored app runs the same scripts automatically once its
models are ready, so the new connection is written without another prompt or a
manifest fetch.

### Failure and rollback

- **Install-command failure** aborts immediately; no model preparation runs.
- **Prepare failure** aborts; prepared bundles stay cached (a re-run resumes).
- **Start/health failure** stops the models started by that run
  (`--keep-partial` keeps them for debugging).
- **Setup-script failure** is written to the app log, stops the remaining
  scripts, and leaves the running app `ready` (the models are not rolled back).
- Re-running `app install` is idempotent: it fills missing prepare steps and
  only re-runs the install script with `--force`; it never starts models.

## Commands

```bash
flashcli app list   [--json]
flashcli app show   <key> [--json]
flashcli app install <key> [--yes|-y] [--dry-run] [--force]
                     [--bundle REF]... [--no-install] [--no-model]
flashcli app status <key> [--json]
flashcli app start|stop|restart <key>
flashcli app logs   <key> [--ref REF] [--lines N] [-f]
flashcli app uninstall <key> [--yes] [--purge-models]
```

Rules:

- Any shell execution requires explicit confirmation; `--yes` runs it without a
  prompt; non-interactive runs without `--yes` skip it and record `skipped`.
- URLs are handled by the client: the CLI prints the link and never downloads;
  the desktop, after confirmation, downloads and runs installers
  (.exe/.msi on Windows, .dmg/.pkg on macOS) and opens plain pages in a browser.
- Bundles are prepared only after the application install succeeded; a failed
  install (script or installer) aborts the whole run.
- Installs are serialized per application; the desktop additionally allows one
  install at a time and disables the other apps while an install job runs (its
  card and the page banner show the progress). Start/stop are serialized per
  application too, so a restore cannot race a manual start.
- Ports are allocated automatically and recorded; `start` is idempotent.
- `uninstall` stops the app's models and removes its state; model caches are kept
  unless `--purge-models` is given.

## Entry points

The CLI, the daemon and the desktop all drive the same `internal/apps` service;
only the way the install-script decision is obtained differs:

| Entry point | Install-script decision |
|---|---|
| `flashcli app install` | asks `[y/N]` on a terminal; `--yes` runs it; no terminal without `--yes` skips and records `skipped` |
| `flashserver` `POST /api/v1/apps/{org}/{name}/install` | body must carry `install_command: "run" \| "skip" \| "client"` (400 otherwise); runs as job `app-install`, prepares models, never starts them |
| `flashserver` `POST /api/v1/apps/{org}/{name}/start` | starts models; body may carry `setup_scripts` + `client_home` for the setup confirmation |
| `flashcli-desktop` 应用页 | 安装 dialog shows the command; 运行脚本并安装 runs it **on the client OS** and then sends `client`, 跳过脚本安装 sends `skip`, 取消 does nothing; 启动 asks which setup scripts to run; job progress is polled into the detail pane |

### Platform ownership

The application and its models live on different platforms: the app is
installed where the user works (for example a Windows exe), while the models
run in WSL/the daemon host. Therefore:

- The manifest platform check and command selection use the **client** platform
  (`client_os`/`client_arch` on the API, the desktop's own OS/arch). Without
  them the daemon falls back to its own platform (CLI behaviour).
- The desktop executes the install command itself (`powershell -Command` on
  Windows, `sh -c` elsewhere) and reports `install_command: "client"`; the
  daemon records the command as executed and never runs a client-side exe.
- Preparing bundles stays with the daemon and is unaffected by the client
  platform. Starting models is a separate action, also on the daemon.

Uninstall is exposed on both fronts (`DELETE /api/v1/apps/{org}/{name}`,
desktop 卸载 with an optional `purge_models`); it never removes the app's own
installed files.

## Local state

Shared by the CLI and the daemon at `$FLASHCLI_HOME/flashserver/apps.json`
(cross-process file lock; atomic rename on write):

```json
{
  "apps": {
    "xym/workbuddy:1.0.0": {
      "version": "1.0.0",
      "state": "prepared",
      "installed_at": "2026-11-17T08:00:00Z",
      "install": {"command": "irm … | iex", "executed": true},
      "models": [
        {"ref": "xym/gemma4_e2b_it:1.0.1", "id": "gemma4_e2b_it",
         "prepared": true}
      ],
      "setup_scripts": ["workbuddy"],
      "setup_plan": [{"key": "workbuddy", "url": "…", "sha256": "…"}],
      "setup_client_home": "C:\\Users\\…",
      "last_log": ["starting …", "setup workbuddy: done"],
      "connection": {}
    }
  }
}
```

Install leaves `state=prepared` with no `pid`/`endpoint`/connection. A successful
start records `state=ready`, the allocated endpoint/port and the connection;
`stop` keeps the entry as `stopped` (models and caches stay).

## Model lifecycle

- `internal/apps` prepares bundles via `internal/host` and starts them via
  `internal/modelrun` (the same supervisor `flashserver` uses).
- Preparing is offline-first: a complete weights cache + download manifest is
  reused without contacting the model hub. Only an explicit `flashcli pull` and
  the desktop's 下载 force a remote re-listing.
- If `flashserver` is running, its `Manager` and `apps` share state: app models
  start through the Manager (same `max_loaded` slots and bundle
  `resources.min_vram_mib` admission as the 模型 page), and `start` reuses the
  recorded pid/port when the model is already resident.
- Applications that declare the same bundle share one resident instance. Each
  application is an owner (the 模型 page is the `model` owner), including when it
  reuses an already healthy instance; stopping an app releases only its own
  claim, and the process stops when the last owner releases it. Unloading from
  the 模型 page is the explicit override that stops it regardless of owners.
- Stopping or uninstalling an app releases its models through the Manager, so
  the slots and the 模型 page list stay accurate even though the daemon builds a
  short-lived app service per request.
- Auto ports are recorded; on restart the recorded port is reused when free.
- On daemon start, apps that were ready with live models are started again
  (models loaded from the 模型 page are restored from
  `~/.flashcli/flashserver/models.json`). This runs in the background through
  normal admission; the OS autostart toggle only decides whether the daemon
  starts at boot.

## Configuration

v1 manifests publish `config: []`; the host does not interpret it. Client
configuration is done by `setup.scripts` (see
[app_manifest_standard.md](app_manifest_standard.md)): after the models are
ready, the confirmed scripts write the application's own config using the
connection. There is no `connection.json` writer.

## Security

- Remote shell installers are shown first and require confirmation; `--yes` is
  the only way to run them unattended.
- URLs are never fetched by the daemon. The desktop downloads an installer only
  after the user confirms it in the dialog (the host is shown), and page links
  open in the browser.
- The local API stays single-user (no remote mode).
- The desktop never guesses about an install script or installer. 安装 opens a
  dialog that shows the command or URL; a script runs and an installer downloads
  only after 运行脚本并安装 / 下载并安装 (跳过 prepares the models without it). The
  daemon enforces this: `POST /api/v1/apps/{org}/{name}/install` requires
  `install_command: "run" | "skip" | "client"` and rejects a missing value, since
  a daemon has no terminal to ask.

## Testing

| Tier | Coverage |
|---|---|
| T1 | manifest parse/validate, platform command precedence, default bundle selection, state lock/round-trip, shared lifecycle with fakes, install endpoint run/skip/decision-required; install leaves `prepared` (no model started); desktop helper unit tests (request body decision, URL vs script, log dedupe/cap, WSL config, `last_log`) |
| T2 | local fake FlashHub (httptest) + real `flashserver`: install → prepared → start → status → stop; install job with `install_command: run`/`skip`/missing (400); `--dry-run`; shell prompt/decline; URL never executed; setup script order/failure/sha256 retry and verified cache; restore replays the saved setup selection offline; interrupted start/install/stop recovery; per-app serialization; service log persistence and WebSocket log stream |
| T3 | `FLASHCLI_FLASHHUB_LIVE=1`: live app list/manifest shape contract |

## Milestones

The app pipeline is complete: `internal/modelrun`, `internal/apps`, the
`flashcli app` commands, the `/api/v1/apps*` handlers and the desktop 应用 page are
implemented and covered by T1/T2 plus the release gate.
