# 开发验证规范

<p align="right"><a href="development_verification_standard.md">English</a> · <strong>简体中文</strong></p>

本文是**合并到 `dev` 之前**验证变更的权威流程。发布门禁是另一套流程，见
[release_verification_standard.zh-CN.md](release_verification_standard.zh-CN.md)。

## 1. 分支与提交规则

- 默认从 `dev` 拉 `feat/<topic>` 或 `fix/<topic>` 分支，PR 回 `dev`。
- 维护者明确要求的**本地、未推送**维护工作可以直接提交在 `dev`；在确认正常
  review/验证路径前不要推送。
- 绝不直接提交 `main`。`dev` → `main` 由维护者批准并 squash-and-record；见
  [CONTRIBUTING.md](../CONTRIBUTING.md#git-workflow)。
- 一个提交只做一个逻辑变更，不要把无关代码、重构和文档混在一起。

## 2. 前置条件

| 要求 | 说明 |
|---|---|
| Go >= 1.24 | 辅助脚本可用 `GO=/path/to/go` 指定二进制。 |
| `flashcli-bundle` 可编辑安装 | `pip install -e "./flashcli-bundle"`（infer 测试加 `[infer,test]`）。 |
| Rust MSVC（仅桌面端） | 在 `desktop/` 执行 `cargo test`。 |
| Linux 或 WSL | 验收测试运行真实 Linux 二进制。 |

只构建测试用二进制：

```bash
bash scripts/build_dev_bins.sh
```

产出 `dist/go/flashcli-linux-amd64` 和 `dist/go/flashserver-linux-amd64`。
**不要**为了测试运行 `scripts/build_go.sh`：它构建 Linux amd64/arm64 和 Windows
setup 发布资产，pytest 一个都用不到。

## 3. 验证分层

| 层级 | 命令 | 何时 |
|---|---|---|
| **1 — 代码**（默认） | `cd go && go test ./...` · `pytest tests/` · `gofmt -l .` | 每次修改 / PR |
| **2 — 验收**（离线） | `bash scripts/verify_e2e.sh` | CLI、daemon API、调度、缓存或桌面接入行为 |
| **2h — 重型验收** | `bash scripts/verify_e2e.sh --heavy` | 合并 `main` 或发布 RC 前 |

第 3 层（`--heavy --network`）是发布门禁，定义见
[release_verification_standard.zh-CN.md](release_verification_standard.zh-CN.md)。

### 第 1 层 — 代码

```bash
cd go
gofmt -w .
go build ./...
go test ./...

pytest tests/            # 协议/infer + conformance；不含 bench、release、network
pytest tests/bench/      # 只在修改 bench 辅助脚本时
cd desktop && cargo test # 只在修改桌面端时
```

第 1 层不启动真实 daemon，也不验证已安装二进制的接口面。仅发布使用的构建检查
（`tests/test_build_go.py`，标记 `release`）在发布门禁中运行；PyPI venv 测试
（`tests/test_bundle_requirement_import.py`，标记 `network`）在第 2h 层运行。

### 第 2 层 — 真实二进制，离线

```bash
bash scripts/verify_e2e.sh
```

`verify_e2e.sh` 会：

1. 用 `scripts/build_dev_bins.sh` 构建两个开发二进制；
2. 导出 `FLASHCLI_GO_BIN` 和 `FLASHSERVER_BIN`；
3. 以 `FLASHCLI_ACCEPTANCE=1` 运行 `pytest tests/acceptance`。

覆盖：

- 真实 `flashcli version/doctor/bundle validate/models show`；
- 通过本地 HTTP index 的离线 FlashHub 同步（两种 CDN layout）；
- 真实 `flashserver`：preload → 网关请求 → 日志 → unload；
- 需要真实 HTTP 服务的 API/settings/错误路径检查。

不运行 Python bundle 推理；那属于 `--heavy` 层。

### 第 2h 层 — 重型验收

```bash
bash scripts/verify_e2e.sh --heavy
```

增加 v3/v4 Python bundle 和 native bundle 的真实 `run`。会创建 bundle venv，并运行
标记为 `network` 的 requirement 测试（PyPI venv 安装），因此需要网络，耗时数分钟；
用于合并 `main` 和发布候选前，不要每次修改都跑。

## 4. 按变更类型检查契约

| 变更 | 必须处理 |
|---|---|
| HTTP API（`/v1/*`、`/api/v1/*`） | 更新 `go/internal/server/openapi.yaml`（**唯一**契约，嵌入并通过 `/openapi.yaml` 提供）；更新 `docs/flashserver-api.md` + `.zh-CN.md`、`go/internal/server/web/docs.html`、桌面调用方和验收/单元测试；grep 旧路径并确认返回 404。 |
| CLI 命令/参数 | 命令帮助 + CLI 测试；命令面变化时更新 `tests/conformance/test_command_parity.py`。 |
| 桌面行为 | `desktop/README.md`、`docs/flashserver-desktop.md` + `.zh-CN.md`、`cargo test`；UI 变化需要构建。 |
| Bundle manifest / 执行 ABI | 权威 spec + `.zh-CN.md`、bundle `README`/`BUILD`、`flashcli bundle validate`、conformance fixtures。 |
| 纯文档 | [documentation_standard.zh-CN.md](documentation_standard.zh-CN.md) 检查清单。 |

不要只改 handler 和单元测试就提交 API 变更：OpenAPI 契约、API 索引、控制台参考页、
桌面调用方和中文镜像都属于同一次变更。

## 5. 过期二进制与环境规则

- 验收会拒绝比 `go/` 源码旧的 `dist/go` 二进制。使用 `--no-build` 时，
  `verify_e2e.sh` 会直接失败，而不是静默测试旧代码。
- 显式设置 `FLASHCLI_GO_BIN` / `FLASHSERVER_BIN` 时视为调用方信任该二进制，跳过
  新鲜度检查。
- `PYTHON_BIN=/path/to/python` 指定 `verify_e2e.sh` 的解释器（pytest 在 venv 中时
  使用）。
- `FLASHCLI_ACCEPTANCE_HOME` 复用 venv/uv 缓存（默认 `/tmp/flashcli-acceptance`）。

## 6. PR 完成标准

- [ ] 第 1 层命令通过。
- [ ] API/CLI/daemon/缓存变更通过第 2 层；合并 `main` 或 RC 前通过第 2h 层。
- [ ] 契约文档和中文镜像已更新；删除的端点返回 404。
- [ ] 没有提交过期的 `dist/go` 二进制、密钥、权重或构建产物。
- [ ] 提交是按逻辑拆分的 Conventional Commits；分支已 rebase 到 `dev`。
- [ ] 文档链接可解析，新文档已加入 `docs/README.md` 索引。

## 7. 失败处理

| 现象 | 处理 |
|---|---|
| 验收提示二进制过期 | 运行 `scripts/build_dev_bins.sh` 后重跑。 |
| 新端点返回 405 而不是 404 | 检查路由顺序/兜底 pattern；把该路径加入验收测试。 |
| 文档/API 不一致 | 先改权威契约，再改索引、控制台和中文镜像。 |
| 偶发或仅环境相关的失败 | 用同一层复现；在 PR 中记录命令和环境。没有实际通过就不得标记为 green。 |
