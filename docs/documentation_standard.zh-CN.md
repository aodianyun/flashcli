# 文档规范

<p align="right"><a href="documentation_standard.md">English</a> · <strong>简体中文</strong></p>

文档存放位置、命名和同步方式的权威规则。新增或移动文档时必须遵守。

## 1. 目录布局

| 位置 | 内容 |
|---|---|
| `docs/` | 权威规范、标准、用户指南和架构文档；一个文件只讲一个概念。 |
| `docs/plans/` | 交付计划与里程碑清单；计划**不是**行为契约。 |
| `docs/README.md` / `docs/README.zh-CN.md` | 文档索引；每个文档都必须登记。 |
| `docs/images/` | 架构图/流程图：手工排版总览 SVG、权威 Graphviz `.dot` 流程源文件、渲染后的 `.svg`/`.png`。要求见 [CONTRIBUTING.md → Architecture and flow diagrams](../CONTRIBUTING.md#architecture-and-flow-diagrams)。 |
| 根目录 `README.md`、`AGENTS.md`、`CONTRIBUTING.md` | 项目概览与贡献规则（不是功能规范）。 |

未经本规范与索引更新，不要在 `docs/` 下新增子目录。

## 2. 命名

| 类型 | 模式 | 示例 |
|---|---|---|
| 权威契约 | `<area>_<topic>_spec.md` | `flashserver_gateway_scheduler_spec.md` |
| 交付计划 | `plans/<area>_<topic>_plan.md` | `plans/flashserver_gateway_scheduler_plan.md` |
| 标准 / 格式 | `<topic>_standard.md` | `bundle_publish_standard.md` |
| 指南 / 教程 | `<topic>_guide.md` | `bundle_builder_guide.md` |
| API 参考 | `<area>-api.md` | `flashserver-api.md` |
| 架构 / 模块图 | `architecture.md`、`module_layers.md` | — |

规则：

- 使用小写 `snake_case`；不要空格、日期、版本号或作者名。
- flashserver 相关的契约、计划和 API 文档必须带 `flashserver` 前缀
  （`flashserver_*`）。
- 计划与其契约使用相同的 `<area>_<topic>` 主干。
- 英文为基本文件名；中文镜像在同一目录追加 `.zh-CN.md`
  （例如 `plans/foo_plan.zh-CN.md`）。

## 3. 权威性

- `docs/` 下的 **spec** 描述必须实现的行为；代码、测试和计划不得与之冲突。
  行为变更必须先更新 spec。
- `docs/plans/` 下的 **plan** 描述交付顺序、里程碑、测试和退出条件，可以在不改变
  契约的前提下调整；plan 与 spec 冲突时以 spec 为准。
- **标准**（`*_standard.md`）定义格式（manifest、应用、执行 ABI）。
- **指南**解释稳定契约的用法，不得自行发明规则。

## 4. 语言镜像

- 除生成文件或第三方文件外，每个英文文档都要在同目录提供 `.zh-CN.md` 镜像。
- 同一次变更中同时更新两种语言。标题、表格和代码块结构保持一致；翻译正文，
  不翻译标识符、路径或命令输出。
- 每个文件顶部放另一个语言的链接。

## 5. 索引与链接

- 每个文档都要登记到 `docs/README.md` 和 `docs/README.zh-CN.md`，写一行用途和读者。
- 使用相对 Markdown 链接。`docs/plans/` 中引用根目录 spec 用 `../<spec>.md`；
  并显式链接中文镜像。
- 不要链接生成文件、`dist/`、构建产物或外部 clone。
- 提交前运行文档链接检查（或等价检查）。

## 6. 内容规则

- 一个文档只讲一个概念；删除或修正过时内容，不要层层叠加说明。
- 先写契约，再写细节和示例。
- 模型专属行为放在 bundle 文档中，不要写进 host 文档。
- 计划必须包含：目标、工作流/里程碑、交付物、测试、退出条件、强制规则。
- 不要在计划里复制 spec；用链接引用。

## 7. 契约文档同步

- `go/internal/server/openapi.yaml` 是 HTTP 契约的**唯一**来源，嵌入 daemon 并通过
  `/openapi.yaml` 提供。不要在 `docs/` 下再存一份。
- 端点或 schema 变更还要更新 `docs/flashserver-api.md` + `.zh-CN.md`，以及内嵌控制台
  参考页 `go/internal/server/web/docs.html`。它们不会从 OpenAPI 自动生成。
- 删除或重命名端点时，全仓搜索旧路径，增加验收测试确认已不可用，并确认返回 404。
- 用户可见变更要写入权威 spec，不能只改 API 参考。

## 8. 文档变更检查清单

- [ ] 目录和文件名符合 §1–§2。
- [ ] 英文与中文镜像同时更新。
- [ ] `docs/README.md` 与 `docs/README.zh-CN.md` 已更新。
- [ ] 相对链接从文件所在目录可解析。
- [ ] spec/plan 的权威性清晰（§3）。
- [ ] 契约文档已按 §7 同步（OpenAPI 副本、API 索引、控制台参考）。
- [ ] 过时内容已删除或修正。
- [ ] 链接检查通过，无断链。
