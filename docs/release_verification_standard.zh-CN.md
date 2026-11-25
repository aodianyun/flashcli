# 发布验证规范

<p align="right"><a href="release_verification_standard.md">English</a> · <strong>简体中文</strong></p>

本文是**host 发布**验证与发布的权威流程。合并前的开发检查见
[development_verification_standard.zh-CN.md](development_verification_standard.zh-CN.md)。

## 1. 范围与前置条件

- 发布只从 **`main`** 出，绝不以 `dev` 发布中间版本。
- `main` 必须干净且等于 `origin/main`；发布脚本会强制检查。
- host 发布是**增量**的：保留所有已发布版本和 tag；只删除未发布的测试/草稿版本。
- 发布门禁必须针对**即将发布的同一个 commit** 通过。

## 2. 版本号

- 在 `dev` 同时修改 `pyproject.toml` 的 `[project].version` 和
  `desktop/Cargo.toml` 的 `version`。桌面端使用三段前缀（例如 `1.0.9`）；不一致会
  导致打包失败。
- host 版本：`X.Y.Z.YYYYMMDD`（日期不带点）。
- tag：`v<version>`（例如 `v1.0.9.20261120`）。
- 提交信息：`chore(release): bump version to X`。

## 3. 门禁与证据

```bash
bash scripts/verify_e2e.sh --heavy --network
```

这是开发规范中的第 3 层：

- 真实二进制和真实 daemon；
- Python bundle 推理（`--heavy`）；
- 实时 FlashHub manifest 检查（`--network`）；
- 仅发布使用的构建/安装检查（`tests/test_build_go.py -m release`）；
- PyPI venv requirement 检查（`tests/test_bundle_requirement_import.py -m network`）；
- 写入 `dist/e2e-pass.json`，记录当前 commit、`heavy=true`、`network=true`。

`scripts/release_go.sh --upload` 只有在标记与当前 HEAD 完全匹配且两个标志都为 true
时才允许发布。`FLASHCLI_SKIP_E2E_GATE=1` 仅用于流水线测试，真实发布绝不使用。

## 4. 发布顺序

1. **在 `dev` 升版本**（§2）并提交。
2. **同步 `dev` → `main`**（squash-and-record）。需要维护者明确批准；未批准不得推送
   `main`。
3. **检查实时 FlashHub index 契约**（只读 index JSON，几 KiB）：

   ```bash
   FLASHCLI_FLASHHUB_LIVE=1 pytest tests/test_flashhub_index_contract.py
   ```

4. **在 `main` 跑完整门禁**（§3）。门禁未绿不得打 tag 或发布。
5. **在 `main` 构建 Windows 安装包：**

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/build_windows_package.ps1
   ```

   该脚本构建桌面客户端、其内嵌的 Go 资产，以及
   `flashcli-desktop-setup-windows-amd64-v<version>.exe`。`go` 不在 PATH 时用
   `-GoBin`。若要嵌入已构建的 Go 资产，先运行 `bash scripts/build_go.sh` 并传
   `-SkipGo`。
6. **准备 release notes**（§5），以上一个已发布版本为基准。
7. **从 `main` 发布：**

   ```bash
   bash scripts/release_go.sh --upload \
     --notes-file <notes.md> \
     --windows-installer dist/windows/flashcli-desktop-setup-windows-amd64-v<version>.exe
   ```

   脚本会校验门禁、`main == origin/main` 且干净，在 HEAD 创建/推送 tag，构建并上传
   Go 资产和 Windows 安装包；GitHub 或 Gitee 任一失败即整体失败。
8. **在干净隔离环境中验证已发布资产：**

   ```bash
   bash scripts/verify_release.sh --version X
   # 验证 Gitee / 国内镜像时加 --mirror
   ```

9. **检查**发布的安装包名称/SHA256，以及两个平台上的
   `flashcli-linux-{amd64,arm64}` 和 `flashserver-*` 是否齐全。

## 5. Release notes 规范

简洁，只写 **Features** 和 **Fixes**。GitHub 与 Gitee 使用同一份文本。内容以**上一个
已发布版本**为基准，而不是 commit 列表。

```markdown
# flashcli <version>

<一行概述；加粗重点>

## Features
- **<area>**: <用户可见的变化>

## Fixes
<!-- 可选：只写 vPREV 中确实坏掉的行为；没有则整节省略 -->
- **<area>**: <原来坏在哪里 → 现在如何>

**Full Changelog**: <compare 或 commits 链接>
```

规则：

- 短条目；不要粘贴原始 commit；不要额外章节。
- **只用英文**；不要写中文摘要行。
- 不要重复资产列表或 SHA256。
- **Feature** 是 `vPREV` 没有的能力；**Fix** 是 `vPREV` 中坏掉、现在修好的行为。
- 去掉内部改动、无可见影响的 refactor、纯测试/文档工作。
- 每条都要能用 diff 或实际运行证明。
- 结尾放 `.../compare/vPREV...vNEW`。

## 6. 资产与命名

| 资产 | 用途 |
|---|---|
| `flashcli-<os>-<arch>` | CLI：pull/run/serve/models/cache/… |
| `flashserver-<os>-<arch>` | 常驻调度器 + 本地控制台 |
| `flashserver-setup-<os>-<arch>` | 安装器后端（Linux systemd、Windows WSL2） |
| `flashcli-desktop-setup-windows-amd64-v<version>.exe` | Windows 桌面安装包 |

- `scripts/build_go.sh` 只构建**发布** Go 资产：Linux amd64/arm64 + Windows setup。
  它不是测试构建。
- 发布资产名**稳定且不带版本号**，版本由 tag 表示。不要给 Go 资产加
  `-v<version>`。
- Linux 资产可复现（`-buildvcs=false`）。Inno Setup 安装包**不是**字节可复现的：
  只构建一次、上传后不要重建。
- 分享稳定链接：

  ```text
  https://github.com/aodianyun/flashcli/releases/latest/download/<name>
  https://gitee.com/aodiansoft/flashcli/releases/download/latest/<name>
  ```

## 7. 失败与中止规则

| 情况 | 处理 |
|---|---|
| 门禁未绿 | 停止。修复后重跑；不得打 tag 或发布。 |
| `dist/e2e-pass.json` 缺失/过期 | 在当前 HEAD 重跑完整门禁。 |
| `main` 不干净或与 `origin/main` 不一致 | 先解决；HEAD 变化后必须重跑门禁。 |
| GitHub 或 Gitee 上传失败 | 脚本会失败；修复凭据后重跑。不要手工修改已发布资产。 |
| Windows 安装包已上传 | 不要重建；只能在上传前重建。 |
| 发布了坏版本 | 用新版本/新 tag 向前修复；绝不重写或删除已发布历史。 |

## 8. 发布后检查清单

- [ ] 发布 commit 的完整门禁已通过（`heavy=true`、`network=true`）。
- [ ] tag `v<version>` 存在于发布 commit 并已推送。
- [ ] GitHub 和 Gitee 都有完整 Go 资产和 Windows 安装包。
- [ ] `verify_release.sh --version X` 通过（Gitee 加 `--mirror`）。
- [ ] 两个平台的 release notes 符合 §5。
- [ ] 稳定下载链接可访问。
- [ ] 下一个开发周期从更新后的 `dev` 开始。
