# FlashHub application install plan

<p align="right"><strong>English</strong> · <a href="application_install_plan.zh-CN.md">简体中文</a></p>

> **Status: design plan; not implemented.** The current flashcli host supports Model
> Bundles and `serve`, but does not yet install or manage external applications.

## 1. Goal

One command installs an application, starts its local model service, configures the
application to use that service, and enables autostart:

```bash
flashcli app install deepseek-harness
```

FlashHub owns the application catalog and version metadata. flashcli fetches the
application by key and executes a bounded, declarative installation plan.

## 2. Terms

| Term | Meaning |
|---|---|
| **Application** | An external product such as `deepseek-harness`, installed and configured by flashcli |
| **App key** | FlashHub application identifier: `[namespace/]name[:version]` |
| **Application manifest** | Declarative install/service/config contract from FlashHub |
| **Model Bundle** | Existing `flashcli-bundle/<name>:<version>` model runtime |
| **App service** | Host-managed process running `flashcli serve <bundle>` |

Applications and Model Bundles are different layers:

```text
Application (deepseek-harness)
  └── references one Model Bundle
        └── runs through flashcli serve
```

## 3. Ownership

| Layer | Responsibility |
|---|---|
| FlashHub | App registry, app keys, immutable versions, manifest validation, artifact metadata |
| flashcli | Resolve app key, install artifact, prepare model, create service, patch config, enable autostart, health check, rollback |
| Bundle | Model entry, runtime, weights, options |
| User | Local login/session, optional FlashHub token, root only for system packages |

## 4. App key

```text
deepseek-harness
aodianyun/deepseek-harness
aodianyun/deepseek-harness:1.0.0
```

- Short key may resolve to a default namespace/latest version.
- Automation and production installs should pin the full version.
- FlashHub returns the canonical key and resolved version.
- An Application Manifest references a pinned Model Bundle ref.

## 5. Flow

```text
User
  │ flashcli app install <key>
  ▼
flashcli
  │ 1. resolve app key
  │ 2. GET app manifest from FlashHub
  ▼
FlashHub
  │ manifest + artifact metadata
  ▼
flashcli
  │ 3. validate manifest, platform, version compatibility
  │ 4. preflight: disk, port, model bundle, system capabilities
  │ 5. install application artifact (sha256 verified)
  │ 6. prepare model bundle / weights / venv
  │ 7. create model service with flashcli serve
  │ 8. patch application configuration atomically
  │ 9. enable autostart
  │ 10. start service and wait for /v1/models
  │ 11. smoke test
  │ 12. write local state
  ▼
User opens the application
```

### Transaction and rollback

```text
PREPARE → INSTALL_APP → PREPARE_MODEL → CREATE_SERVICE
        → PATCH_CONFIG → ENABLE_AUTOSTART → START → HEALTHY
```

On failure: stop the new service, remove the new unit/state, restore the previous
configuration backup, and optionally remove the installed application.

## 6. FlashHub API

### 6.1 Resolve/read an app

```http
GET /api/v1/apps/{namespace}/{name}:{version}
Authorization: Bearer <FLASHCLI_FLASHHUB_TOKEN>
```

Response envelope:

```json
{
  "code": 0,
  "data": {
    "app_key": "aodianyun/deepseek-harness",
    "resolved_version": "1.0.0",
    "manifest_url": "https://.../application.json",
    "manifest": {
      "format": "flashcli-application",
      "app_format_version": 1,
      "protocol_version": 1
    }
  }
}
```

Additional management/read endpoints:

```text
GET /api/v1/apps
GET /api/v1/apps/{namespace}/{name}
GET /api/v1/apps/{namespace}/{name}/versions
GET /api/v1/apps/{namespace}/{name}:{version}
```

The app manifest is data only. FlashHub MUST NOT return arbitrary shell commands.

## 7. Application Manifest

```json
{
  "format": "flashcli-application",
  "app_format_version": 1,
  "protocol_version": 1,
  "name": "deepseek-harness",
  "version": "1.0.0",
  "display_name": "DeepSeek Harness",
  "supported": {
    "os": ["linux", "darwin", "windows"],
    "arch": ["x86_64", "arm64"]
  },
  "install": {
    "kind": "github-release",
    "repo": "owner/deepseek-harness",
    "version": "v1.0.0",
    "asset": "deepseek-harness-{os}-{arch}.tar.gz",
    "sha256": "sha256:...",
    "install_dir": "~/.local/share/deepseek-harness"
  },
  "model": {
    "bundle": "flashcli-bundle/qwen3_8b_nvfp4:1.0.0",
    "serve": {
      "host": "127.0.0.1",
      "port": 18100,
      "options": {
        "model_name": "deepseek-harness",
        "max_seq": 8192
      }
    },
    "health": {
      "url": "http://127.0.0.1:{port}/v1/models",
      "timeout_sec": 120
    }
  },
  "config": [
    {
      "kind": "json",
      "path": "~/.config/deepseek-harness/config.json",
      "merge": {
        "model.base_url": "http://127.0.0.1:{port}/v1",
        "model.api_key": "local",
        "model.name": "{model_name}"
      },
      "backup": true
    }
  ],
  "service": {
    "kind": "auto",
    "name": "flashcli-model-deepseek-harness",
    "autostart": true,
    "restart": "on-failure",
    "command": [
      "flashcli", "serve", "{bundle}",
      "--host", "{host}", "--port", "{port}"
    ]
  },
  "system": {
    "requires": ["c-compiler", "python-headers"]
  }
}
```

### 7.1 Field reference

| Field | Required | Description |
|---|---|---|
| `format` | yes | Must be `flashcli-application` |
| `app_format_version` | yes | Application manifest schema version; first phase is `1` |
| `protocol_version` | yes | FlashHub/application protocol version; first phase is `1` |
| `name` | yes | Application name; canonical key is returned by FlashHub |
| `version` | yes | Immutable application version |
| `display_name` | recommended | Human-readable application name |
| `supported.os` | yes | Supported operating systems |
| `supported.arch` | yes | Supported CPU architectures |
| `install.kind` | yes | Allowlisted installer kind (`github-release`, `archive`, `npm`, `pipx`, `homebrew`, `winget`, `docker`) |
| `install.repo` | conditional | Source repository for artifact-based installers |
| `install.version` | conditional | Upstream artifact version/tag |
| `install.asset` | conditional | Artifact filename template; supports `{os}` and `{arch}` |
| `install.sha256` | yes for downloads | Artifact checksum; host must verify before install |
| `install.install_dir` | recommended | User-local install destination |
| `model.bundle` | yes | Pinned Model Bundle ref used by the app |
| `model.serve.host` | yes | Model service bind host; default should be `127.0.0.1` |
| `model.serve.port` | yes | Requested service port; host resolves conflicts |
| `model.serve.options` | optional | Options forwarded to the model bundle `serve` entry |
| `model.health.url` | yes | Readiness URL; supports `{host}` and `{port}` |
| `model.health.timeout_sec` | optional | Maximum readiness wait |
| `config[].kind` | yes | Allowlisted adapter (`json`, `yaml`, `toml`, `env`, `ini`, `command-args`) |
| `config[].path` | yes | User configuration file or environment file |
| `config[].merge` | conditional | Declarative key/value patch; placeholders are expanded by host |
| `config[].backup` | recommended | Back up the previous file before writing; default `true` |
| `service.kind` | yes | `auto` (or a supported service backend) |
| `service.name` | yes | Stable local service name |
| `service.autostart` | yes | Enable the service at login/boot according to host policy |
| `service.restart` | optional | Restart policy (`on-failure`, `always`, `no`) |
| `service.command` | yes | Restricted template that invokes `flashcli serve`; never arbitrary shell |
| `system.requires` | optional | Host capabilities required by the app, e.g. `c-compiler`, `python-headers` |

Template placeholders:

```text
{os}          supported OS name
{arch}        supported CPU architecture
{bundle}      model.bundle
{host}        resolved model service host
{port}        resolved model service port
{model_name}  resolved model name
{base_url}    http://{host}:{port}/v1
{api_key}     generated/local API key
```

Allowed installers first phase:

```text
github-release
archive
npm
pipx
homebrew
winget
docker
```

Allowed config adapters first phase:

```text
json
yaml
toml
env
ini
command-args
```

## 8. flashcli commands

Only the `flashcli app` command group is supported. There is deliberately no
`flashcli install` alias, because it conflicts conceptually with host installation.

```bash
flashcli app show <app-key>
flashcli app install <app-key> [options]
flashcli app start <app-key>
flashcli app stop <app-key>
flashcli app restart <app-key>
flashcli app status <app-key>
flashcli app logs <app-key>
flashcli app uninstall <app-key>
```

`app install` options:

```text
--version VERSION
--model BUNDLE_REF        # override manifest model ref
--port PORT               # override service port
--no-autostart
--dry-run
--force
--yes
```

`--dry-run` prints the resolved plan without modification.

## 9. Local state

```text
~/.flashcli/apps/<namespace>/<name>/<version>/
  state.json
  service.json
  config-backup/
  logs/
```

State includes the resolved app key/version, artifact hash, model ref, service name,
port, config backup path, status, and timestamps. Re-running install is idempotent.

## 10. Model service and autostart

Linux first phase: systemd user service.

```text
~/.config/systemd/user/flashcli-model-<app>.service
ExecStart=flashcli serve <bundle> --host 127.0.0.1 --port <port>
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now flashcli-model-<app>.service
```

Boot without login requires `loginctl enable-linger <user>` and must be explicit.
macOS LaunchAgent and Windows Task Scheduler are later phases.

## 11. Config patch rules

- Back up the existing file.
- Preserve unknown keys.
- Write atomically.
- Provide placeholders: `{port}`, `{base_url}`, `{model_name}`, `{api_key}`.
- Never execute a bundle-provided shell command.
- Restore the backup on rollback.

## 12. Health and errors

Health default: `GET /v1/models` on the local service.

Stable error codes:

```text
APP_NOT_FOUND
APP_VERSION_NOT_FOUND
UNAUTHORIZED
APP_PLATFORM_UNSUPPORTED
ARTIFACT_HASH_MISMATCH
MODEL_NOT_AVAILABLE
SYSTEM_CAPABILITY_MISSING
PORT_BUSY
CONFIG_PATCH_FAILED
SERVICE_START_FAILED
HEALTH_TIMEOUT
ROLLBACK_FAILED
```

Every failure reports the stage, app key/version, model ref, service name, config path,
reason, and rollback result.

## 13. Security

- No arbitrary shell from FlashHub manifests.
- Only allowlisted installers/adapters.
- Verify artifact sha256.
- Bind model service to loopback by default.
- Do not auto-install system packages unless the bundle's System Requirements policy
  permits it.
- Do not require root for app installation; app files and services should be user-local.
- Do not use backend-provided arbitrary package names.

## 14. Implementation phases

1. Application API + manifest schema + validation.
2. `flashcli app show/install --dry-run`.
3. GitHub-release/archive install and local state.
4. Model service creation + systemd user service.
5. JSON/YAML/TOML/env config adapters.
6. Health check, rollback, uninstall.
7. macOS/Windows service backends.

## 15. Open decisions

- Whether anonymous app metadata is public.
- Port allocation policy (fixed vs first-free, persisted).
- Whether one model service can be shared by multiple applications.
- Whether app manifests require signatures in addition to sha256.
