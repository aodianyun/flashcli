# FlashHub 应用安装计划

<p align="right"><a href="application_install_plan.md">English</a> · <strong>简体中文</strong></p>

> **状态：设计已确认，尚未实现。** manifest 规范见
> [app_manifest_standard.zh-CN.md](app_manifest_standard.zh-CN.md)（v1，与 FlashHub 实际一致）。

## 目标

一条命令完成应用安装、模型准备并保持可用：

```bash
flashcli app install xym/workbuddy
```

`flashcli` 必须能在**没有** `flashserver` 运行时独立工作；守护进程与 CLI 共用同一套
Go 实现（`internal/apps`），桌面只通过 HTTP 访问守护进程。

## 术语

| 术语 | 含义 |
|---|---|
| **Application** | FlashHub 上发布的外部应用（如 `xym/workbuddy`） |
| **App key** | `[namespace/]name[:version]` |
| **Manifest** | `flashcli-application` 文档（见规范） |
| **Model bundle** | 现有 `flashcli-bundle/<name>:<version>` 运行时 |
| **常驻守护进程** | `flashserver`（调度器、控制台、API，保持不变） |

## 职责

| 组件 | 负责 |
|---|---|
| FlashHub | 应用注册、版本、manifest 校验、元数据 |
| `internal/apps`（共享） | manifest 使用、安装策略、应用状态、模型准备与生命周期 |
| `internal/modelrun`（共享） | 监管 `flashcli serve` 子进程（端口、健康、日志、停止） |
| `flashcli` CLI | 用户交互、确认、退出码、JSON 输出 |
| `flashserver` | 供桌面使用的 HTTP API；调用同一共享包 |
| `flashcli-desktop` | 仅 UI；HTTP/WS 访问 `flashserver` |

CLI 的应用操作**不需要**（也不使用）对守护进程的 HTTP 调用。

## App key

`xym/workbuddy` 解析最新版本；`xym/workbuddy:1.0.0` 固定版本。
`flashcli app install` 会记录解析出的版本。

## Manifest

`GET /api/v1/apps/{namespace}/{name}[:version]` 返回 manifest。host 校验
`format`、`app_format_version`、`protocol_version`、必填字段，以及 `name`/`version`
与 key 一致。详见 [app_manifest_standard.zh-CN.md](app_manifest_standard.zh-CN.md)。

## 安装流程

每一步都持久化状态，便于 `status` 观察与失败后重入：

```text
RESOLVE → VALIDATE → PLATFORM → PREFLIGHT → PLAN
  → CONFIRM_INSTALL（仅 shell）
  → INSTALL_APP（URL：manual | shell：执行）
  → PREPARE_MODELS（所有 default bundle，串行）
  → START_MODELS（作为一组，自动端口）
  → HEALTH（逐个模型）
  → APPLY_CONFIG（v1 跳过）
  → READY
```

```mermaid
sequenceDiagram
  autonumber
  participant U as 用户
  participant CLI as flashcli app install
  participant A as internal/apps
  participant FH as FlashHub
  participant H as internal/host + modelrun
  participant REG as apps.json（加锁）

  U->>CLI: app install xym/workbuddy [--yes] [--dry-run]
  CLI->>A: Install(ref, opts)
  A->>FH: GET /api/v1/apps/xym/workbuddy
  FH-->>A: manifest v1
  A->>A: 校验 + 平台判断 + 预检
  alt 不支持或非法
    A-->>CLI: 报错（无任何改动）
  end
  alt install 命令是 URL
    A-->>CLI: 打印链接（手动安装）
    A->>REG: install=manual
  else install 命令是 shell
    A->>U: 展示命令并询问 [y/N]
    Note over A: 非交互且无 -y：跳过并记录
    U-->>A: 同意
    A->>A: 执行（sh -c / powershell -Command）
    A->>REG: install=executed
  end
  loop 每个 default bundle（串行）
    A->>H: prepare = 同步 bundle + venv + 权重
    H-->>A: 进度
    A->>REG: bundle=prepared
  end
  A->>H: 按组启动（自动分配端口）
  loop 每个 bundle
    H-->>A: pid + endpoint
    A->>H: 健康检查
    A->>REG: model=running
  end
  opt 任一启动/健康失败
    A->>H: 停止本次启动的模型
    A->>REG: state=FAILED
  end
  A->>A: APPLY_CONFIG（v1 跳过）
  A->>REG: state=READY + connection
  A-->>CLI: base_url / 模型 id / 状态目录
```

### 状态机

```mermaid
stateDiagram-v2
  [*] --> RESOLVING
  RESOLVING --> PLANNED: manifest 合法、平台支持
  RESOLVING --> FAILED: manifest 非法或平台不支持
  PLANNED --> INSTALLING: 确认执行 shell 命令
  PLANNED --> PREPARING: URL 或跳过脚本
  INSTALLING --> PREPARING: 命令成功
  INSTALLING --> FAILED: 命令失败（终止）
  PREPARING --> PREPARED: 所有 default bundle 就绪
  PREPARING --> FAILED: 某个 bundle 失败（终止）
  PREPARED --> STARTING: 按组启动
  STARTING --> READY: 全部健康
  STARTING --> FAILED: 任一失败（回滚已启动模型）
  READY --> STOPPED: app stop
  STOPPED --> READY: app start
  READY --> [*]: app uninstall
```

### 失败与回滚

- **脚本失败**立即终止，不再准备模型
- **准备失败**终止；已准备的 bundle 保留缓存，重跑可续
- **启动/健康失败**停止本次已启动的模型（`--keep-partial` 保留用于排查）
- 重复执行 `app install` 幂等：补齐缺失步骤、复用运行中的模型；只有 `--force`
  才会重跑安装脚本

## 命令

```bash
flashcli app list   [--json]
flashcli app show   <key> [--json]
flashcli app install <key> [--yes|-y] [--dry-run] [--force]
                     [--bundle REF]... [--no-install] [--no-model] [--no-start]
                     [--keep-partial]
flashcli app status <key> [--json]
flashcli app start|stop|restart <key>
flashcli app logs   <key> [--ref REF] [--lines N] [-f]
flashcli app uninstall <key> [--yes] [--purge-models]
```

规则：

- 任何 shell 执行都要显式确认；`--yes` 免询问；非交互无 `--yes` 时跳过并记 `skipped`
- URL 只打印，host 不自动下载
- 端口自动分配并记录；`start` 幂等
- `uninstall` 停止该应用模型并移除状态；默认保留模型缓存（`--purge-models` 才清理）

## 本地状态

CLI 与守护进程共享 `$FLASHCLI_HOME/flashserver/apps.json`（跨进程文件锁；写入原子
rename）：

```json
{
  "apps": {
    "xym/workbuddy": {
      "version": "1.0.0",
      "state": "ready",
      "installed_at": "2026-11-17T08:00:00Z",
      "install": {"command": "irm … | iex", "executed": true},
      "models": [
        {"ref": "xym/gemma4_e2b_it:1.0.1", "id": "gemma4_e2b_it",
         "port": 18100, "endpoint": "http://127.0.0.1:18100"}
      ],
      "connection": {"base_url": "http://127.0.0.1:18100/v1", "api_key": "local"}
    }
  }
}
```

## 模型生命周期

- `internal/apps` 通过 `internal/host` 准备 bundle，通过 `internal/modelrun` 启动
  （与 `flashserver` 使用同一个监管器）
- `flashserver` 在运行时，其 `Manager` 与 `apps` 共享状态：`start` 发现记录中的
  pid/端口存活则复用，不重复拉起
- 自动端口会记录；重启时优先复用，被占用才重新分配

## 配置（待定）

v1 的 manifest 发布 `config: []`。host 只写 `connection.json`（base URL、模型 id、
`api_key=local`），不修改应用文件。后续 `config` schema 会定义适配器
（`json`/`yaml`/`env`/…）并带备份与回滚。

## 安全

- 远程 shell 安装器先展示再确认；`--yes` 是唯一的免交互方式
- URL 由用户打开，host 不主动下载
- 本地 API 保持单用户（不做 remote 模式）
- 第一期桌面不执行安装脚本：只打开下载页、复制命令；执行统一在 CLI

## 测试

| 级别 | 覆盖 |
|---|---|
| T1 | manifest 解析/校验、平台命令优先级、default bundle 选择、状态锁/读写、共享生命周期的 fake 测试 |
| T2 | 本地假 FlashHub（httptest）+ 真 `flashserver`：prepare → start → status → stop；`--dry-run`；无 `--yes` 跳过 shell；URL 不执行 |
| T3 | `FLASHCLI_FLASHHUB_LIVE=1`：线上应用列表/manifest 形状契约 |

## 里程碑

1. **M1** —— 从 server 抽取 `internal/modelrun`；`server` 改用它（现有测试保持全绿）
2. **M2** —— `internal/apps`：manifest、安装策略、加锁注册表、`Prepare`
3. **M3** —— `internal/apps`：`Start`/`Stop`/`Status`/`Uninstall`（自动端口 + 回滚）
4. **M4** —— `flashcli app` 命令组（直接调用 `internal/apps`）
5. **M5** —— `flashserver` `/v1/apps*`（薄封装）与桌面「应用」Tab
6. **M6** —— 文档、OpenAPI、T1/T2/T3、发布门禁
