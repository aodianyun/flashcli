# FlashHub 应用安装计划

<p align="right"><a href="application_install_plan.md">English</a> · <strong>简体中文</strong></p>

> **状态：设计计划，尚未实现。** 当前 flashcli 只支持 Model Bundle 和 `serve`，还没有外部应用的安装与生命周期管理。

## 1. 目标

一条命令完成应用安装、本地模型服务启动、应用配置修改和自启动：

```bash
flashcli app install deepseek-harness
```

FlashHub 负责应用上架、版本和元数据；flashcli 按 key 获取应用并执行受控的声明式安装流程。

## 2. 术语

| 术语 | 含义 |
|---|---|
| **Application** | `deepseek-harness` 这类外部应用 |
| **App key** | FlashHub 应用标识：`[namespace/]name[:version]` |
| **Application manifest** | FlashHub 返回的声明式安装/服务/配置协议 |
| **Model Bundle** | 现有 `flashcli-bundle/<name>:<version>` 模型运行时 |
| **App service** | host 管理的 `flashcli serve <bundle>` 进程 |

```text
Application (deepseek-harness)
  └── 引用一个 Model Bundle
        └── 通过 flashcli serve 运行
```

## 3. 职责边界

| 层 | 职责 |
|---|---|
| FlashHub | 应用注册、app key、不可变版本、manifest 校验、artifact 元数据 |
| flashcli | 解析 key、安装 artifact、准备模型、创建服务、修改配置、自启动、健康检查、回滚 |
| Bundle | 模型 entry、runtime、权重、选项 |
| 用户 | 本地登录态、可选 FlashHub token；只有系统包需要 root |

## 4. App key

```text
deepseek-harness
aodianyun/deepseek-harness
aodianyun/deepseek-harness:1.0.0
```

- 短 key 可由 FlashHub 解析为默认 namespace / 最新版本
- 自动化和生产安装应固定完整版本
- FlashHub 返回 canonical key 和 resolved version
- Application Manifest 引用固定 Model Bundle ref

## 5. 安装流程

```text
用户
  │ flashcli app install <key>
  ▼
flashcli
  │ 1. 解析 app key
  │ 2. 从 FlashHub 获取 app manifest
  ▼
FlashHub
  │ manifest + artifact metadata
  ▼
flashcli
  │ 3. 校验 manifest / 平台 / 版本
  │ 4. 预检查：磁盘、端口、模型 bundle、system capabilities
  │ 5. 下载并校验应用 artifact（sha256）
  │ 6. 准备模型 bundle / 权重 / venv
  │ 7. 创建模型服务（flashcli serve）
  │ 8. 原子修改应用配置
  │ 9. 注册自启动
  │ 10. 启动服务并等待 /v1/models
  │ 11. smoke test
  │ 12. 写入本地 state
  ▼
用户打开应用
```

### 事务与回滚

```text
PREPARE → INSTALL_APP → PREPARE_MODEL → CREATE_SERVICE
        → PATCH_CONFIG → ENABLE_AUTOSTART → START → HEALTHY
```

任一步失败：

- 停止新服务
- 删除新 service unit / state
- 恢复配置备份
- 可选卸载刚安装的应用

## 6. FlashHub API

### 6.1 获取应用

```http
GET /api/v1/apps/{namespace}/{name}:{version}
Authorization: Bearer <FLASHCLI_FLASHHUB_TOKEN>
```

响应：

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

其他管理/查询接口：

```text
GET /api/v1/apps
GET /api/v1/apps/{namespace}/{name}
GET /api/v1/apps/{namespace}/{name}/versions
GET /api/v1/apps/{namespace}/{name}:{version}
```

manifest 只能是声明式数据，不能返回任意 shell。

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

### 7.1 字段逐项说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `format` | 是 | 固定为 `flashcli-application` |
| `app_format_version` | 是 | Application manifest schema 版本；第一期 `1` |
| `protocol_version` | 是 | FlashHub/application 协议版本；第一期 `1` |
| `name` | 是 | 应用名；canonical key 由 FlashHub 返回 |
| `version` | 是 | 不可变应用版本 |
| `display_name` | 建议 | 人类可读名称 |
| `supported.os` | 是 | 支持的 OS |
| `supported.arch` | 是 | 支持的 CPU 架构 |
| `install.kind` | 是 | 白名单安装器：`github-release` / `archive` / `npm` / `pipx` / `homebrew` / `winget` / `docker` |
| `install.repo` | 条件 | artifact 安装器的源码仓库 |
| `install.version` | 条件 | 上游 artifact 版本/tag |
| `install.asset` | 条件 | artifact 文件名模板，支持 `{os}` / `{arch}` |
| `install.sha256` | 下载安装必填 | artifact 校验值；安装前必须验证 |
| `install.install_dir` | 建议 | 用户本地安装目录 |
| `model.bundle` | 是 | 应用使用的固定 Model Bundle ref |
| `model.serve.host` | 是 | 模型服务监听地址，默认应为 `127.0.0.1` |
| `model.serve.port` | 是 | 请求端口；host 负责冲突处理 |
| `model.serve.options` | 否 | 传给 bundle `serve` entry 的选项 |
| `model.health.url` | 是 | readiness URL；支持 `{host}` / `{port}` |
| `model.health.timeout_sec` | 否 | 最长等待时间 |
| `config[].kind` | 是 | 白名单 adapter：`json` / `yaml` / `toml` / `env` / `ini` / `command-args` |
| `config[].path` | 是 | 用户配置文件或环境文件 |
| `config[].merge` | 条件 | 声明式 key/value patch；host 展开占位符 |
| `config[].backup` | 建议 | 修改前备份；默认 `true` |
| `service.kind` | 是 | `auto` 或支持的 service backend |
| `service.name` | 是 | 稳定的本地服务名 |
| `service.autostart` | 是 | 是否按 host 策略注册登录/开机自启动 |
| `service.restart` | 否 | 重启策略：`on-failure` / `always` / `no` |
| `service.command` | 是 | 受限模板，只允许生成 `flashcli serve` 命令，不能是任意 shell |
| `system.requires` | 否 | 应用需要的宿主能力，如 `c-compiler`、`python-headers` |

模板占位符：

```text
{os}          支持的 OS
{arch}        支持的 CPU 架构
{bundle}      model.bundle
{host}        model service host
{port}        model service port
{model_name}  model name
{base_url}    http://{host}:{port}/v1
{api_key}     生成/本地 API key
```

第一期安装器白名单：

```text
github-release
archive
npm
pipx
homebrew
winget
docker
```

第一期配置 adapter：

```text
json
yaml
toml
env
ini
command-args
```

## 8. flashcli 命令

仅支持 `flashcli app` 命令组。刻意不提供 `flashcli install` 别名，避免和 host 安装语义混淆。

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

`app install` 参数：

```text
--version VERSION
--model BUNDLE_REF        # 覆盖 manifest 中的模型 ref
--port PORT               # 覆盖服务端口
--no-autostart
--dry-run
--force
--yes
```

`--dry-run` 只输出安装计划，不修改系统。

## 9. 本地状态

```text
~/.flashcli/apps/<namespace>/<name>/<version>/
  state.json
  service.json
  config-backup/
  logs/
```

包含 app key/version、artifact hash、model ref、service name、port、配置备份路径、状态和时间。重复 install 应幂等。

## 10. 模型服务与自启动

Linux 第一期使用 systemd user service：

```text
~/.config/systemd/user/flashcli-model-<app>.service
ExecStart=flashcli serve <bundle> --host 127.0.0.1 --port <port>
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now flashcli-model-<app>.service
```

重启后不登录也启动需要显式：

```bash
loginctl enable-linger <user>
```

macOS LaunchAgent / Windows Task Scheduler 放到后续阶段。

## 11. 配置修改规则

- 修改前备份
- 保留未知字段
- 原子写入
- 支持 `{port}`、`{base_url}`、`{model_name}`、`{api_key}` 占位符
- 不执行 bundle 提供的外部命令
- 回滚时恢复备份

## 12. 健康检查与错误码

默认健康检查：本地服务 `GET /v1/models`。

稳定错误码：

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

失败必须输出 stage、app key/version、model ref、service name、配置路径、原因和回滚结果。

## 13. 安全

- 不允许 FlashHub manifest 提供任意 shell
- 只允许白名单安装器和配置 adapter
- artifact 必须校验 sha256
- 模型服务默认只监听 loopback
- 系统包安装必须遵守 bundle System Requirements 策略
- 应用安装默认不需要 root
- 不接受 backend 提供的任意包名

## 14. 实施阶段

1. Application API + manifest schema + validation
2. `flashcli app show/install --dry-run`
3. GitHub-release/archive 安装和本地 state
4. 模型服务 + systemd user service
5. JSON/YAML/TOML/env 配置 adapter
6. 健康检查、回滚、卸载
7. macOS/Windows service backend

## 15. 待确认

- 匿名是否可以访问公开 app metadata
- 端口固定分配还是自动选择并持久化
- 一个模型服务是否允许多个应用共享
- app manifest 是否还需要签名
