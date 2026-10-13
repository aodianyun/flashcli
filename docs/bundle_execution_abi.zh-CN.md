# Bundle 执行 ABI（语言无关）

<p align="right"><a href="bundle_execution_abi.md">English</a> · <strong>简体中文</strong></p>

flashcli **如何调用某个 bundle 的推理入口**的权威契约，且与实现语言无关。当前所有 bundle 都是 Python（`python -m flashcli_bundle.infer`）；本文新增一层语言无关的抽象，使 bundle 可以改为交付原生进程或原生库 —— 且**不改变用户输入的命令**。

相关文档：[bundle_publish_standard.md](bundle_publish_standard.md)（manifest 字段）、[architecture.md](architecture.md)（运行时流程）、[module_layers.md](module_layers.md)（模块分层）。

---

## 1. 范围与非目标

**范围内。** `entry` 契约、新增的 `kind` 选择器、manifest 版本轴，以及每种 kind 必须遵守的生命周期 / 环境变量 / IO 规则。host 读取 manifest 后驱动 bundle 声明的 kind。

**非目标。**

- host 对用户保持不变：`flashcli run|serve|pull|doctor|venv <ref>` 不变。`kind` 是 manifest 细节，永远不是用户参数。
- 本文**不**定义模型计算。原生 producer 负责自己的前向（FlashRT / FlashRT-Nexus）；flashcli 只做编排。
- Python backend 的既有行为（engine/script 模式、`RunEngine`/`ServeEngine`）不变，仍是兼容基线。

---

## 2. 版本轴

三个相互独立、只增不改的版本。当 host 理解的各版本轴都匹配时，必须接受该 bundle；遇到**新的**未知值则硬报错并提示升级。

| 字段 | 位置 | 含义 | 当前值 |
|------|------|------|--------|
| `protocol_version` | manifest 顶层（既有） | `flashcli_bundle` Python 协议（manifest/preset 类型） | `1` |
| `runtime_abi_version` | manifest 顶层（新增） | 原生**模型运行时**face（`frt_model_runtime_v1`） | `1` |
| `exec_protocol_version` | manifest 顶层（新增） | 原生**进程**帧协议（`native-exec`） | `1` |

规则：

- 每个 bundle 都必须有 `protocol_version`（已强制）。
- 当任意 `entry.*.kind == "native-abi"` 时，`runtime_abi_version` **必填**；否则必须缺省。
- 当任意 `entry.*.kind == "native-exec"` 时，`exec_protocol_version` **必填**；否则必须缺省。
- 取值必须等于 host 支持的常量。`runtime_abi_version` 对应 `FRT_MODEL_RUNTIME_ABI_VERSION`（`/app/FlashRT/runtime/include/flashrt/model_runtime.h`，当前 `1u`）。

---

## 3. `entry.kind`

`entry` 保持既有形状，每个 capability 块新增一个可选字段来选择 backend。

```jsonc
"entry": {
  "kind": "python",              // 可选；两个 capability 的默认值
  "native": { /* 共享原生 spec，见 §6/§7 */ },
  "run":   { "module": "run",   "attr": "RunEngine" },
  "serve": { "module": "serve", "attr": "ServeEngine" }
}
```

| `kind` | 含义 | 选用章节 | 引入 |
|--------|------|----------|------|
| `python` | 通过 bundle venv re-exec 的进程内 Python 入口（默认） | §5 | v0（不变） |
| `native-exec` | host 启动独立可执行文件，经 stdio 或 HTTP 通信 | §6 | 本规范 |
| `native-abi` | host `dlopen` 模型运行时 `.so` 并在进程内驱动 | §7 | 本规范 |

**解析（按 capability）：**

1. `kind = block.kind`（若有），否则 `entry.kind`，否则 `"python"`。
2. 单个 capability 可以覆盖 entry 级 kind（例如 `run` 用原生、`serve` 用 python）。
3. 原生配置 = `block.native` 深合并到 `entry.native` 之上（对象合并；标量/列表替换）。`block` 优先。
4. `kind == "python"` 时，`module`/`attr`（及可选 `mode`）与今天完全相同、必填。
5. `kind != "python"` 时，原生 spec 必须可解析；Python 专属字段（`module`/`attr`/`mode`）若存在则忽略。
6. 未知 `kind` 为**硬错误**（绝不静默回退到 Python）。

capability 仍按 `entry` 推断：`run` 块启用 `flashcli run`，`serve` 块启用 `flashcli serve`。

**variants 可覆盖 `entry`。** `variants.<name>.entry` 对顶层 `entry` 做深合并（对象合并、标量/数组覆盖），按 capability 生效。这样同一个 bundle 可以让同一份权重通过不同后端暴露，用既有 `@variant` 后缀选择——例如同一权重同时提供 `@abi`（native-abi）与 `@exec`（native-exec）。生效 entry 在选定 variant 之后解析；版本轴校验会遍历所有 variant 的生效 entry。

### 3.1 仅原生 bundle 作者清单

**仅原生** bundle（无 Python entry）需发布：

- `flashcli-bundle.json`：`format_version: 3`、`protocol_version: 1`；`entry.kind = native-abi|native-exec`；对应的原生版本轴（`runtime_abi_version` 和/或 `exec_protocol_version` = `1`）；`runtime` map 用**无 py** 的 key（`sm{SM}-cu{CUDA}-{os}-{arch}`）；`weights`；以及 `run_options`/`serve_options`。**省略** `python_abi`、`python_dependencies`、`flash_rt/`。
- `runtime/<env-key>/substrate/`：model-runtime `.so`。`native-abi` 放导出 `frt_model_runtime_open_v1` 的 producer `.so`（及 `preload` 库）；`native-exec` 放由 `native.command` 引用的可执行文件（任意语言）。
- **模型专属细节全部归 bundle**（预处理、模态形状/dtype、默认值、option→端口映射）；host 是通用的，不得写死这些（§4）。

`native-abi` 也可声明 `native.session_library` + `loader_symbol`，经 Nexus 内嵌 session 驱动（§7.6）。`native-exec` 除 `native.command` 外不需要知道任何东西；进程讲 NDJSON `stdio` 或 `http`（§6）。

---

## 4. 公共生命周期（所有 kind）

调用时，host 已完成：解析 ref、同步 bundle 树、选择匹配的 `runtime/<env-key>/`、创建 bundle venv（Python kind 仍需建 infer venv，且 Python 是通用运行时）、下载并校验权重、应用 manifest `env`。kind 仅改变**入口如何启动与驱动**。

共享保证：

- **与模型无关的 host。** 所有模型专属细节——预处理/后处理、模态形状/dtype、默认值、option→端口映射——都由 bundle 声明：`run_options`/`serve_options`、manifest `native` 块、以及运行时自身的端口描述符。host 只按声明的端口构造 ABI 载荷，**不得**写死某模型的常量、形状或预处理。
- **权重路径**遵循 [bundle_publish_standard.md](bundle_publish_standard.md) §4.4.1。类 script 的原生启动（即 `native-exec`）收到同样的 `FLASHCLI_CHECKPOINT` / `FLASHCLI_BUNDLE_ROOT` / `FLASHCLI_PRESET` / `FLASHCLI_VARIANT` / `FLASHCLI_EXTRA_WEIGHT_<KEY>` 变量。`native-abi` 通过 `open_symbol` 的 `config_json` 收到 checkpoint 路径。
- **`run_options` / `serve_options`** 仍是默认值与 `--help` 的唯一来源，与 kind 无关。host 将其映射到原生调用（payload 字段或 CLI 参数）。
- **推理期权重离线**：`HF_HUB_OFFLINE=1` 语义对 Python 及任何 hub 访问生效；缺失资源由 `flashcli pull` 修复，而非推理期。
- **退出/就绪**：backend 非零退出或就绪失败时，host 以 CLI 错误暴露；绝不在 backend 崩溃时报告成功。

---

## 5. `python` backend（基线，不变）

host re-exec 进 bundle venv，运行 `python -m flashcli_bundle.infer run|serve`，使用 `entry.<cap>.module` / `.attr` / `.mode`。engine/script 环境规则（§4.4）不变。没有 `entry.kind` 的 bundle 行为与以往完全一致 —— **这是对所有既有 bundle 的兼容保证。**

---

## 6. `native-exec` backend

host 启动外部进程，经带帧的通道通信。这是**进程**通道：故障隔离强、语言自由，代价是序列化。

### 6.1 原生 spec

```jsonc
"entry": {
  "kind": "native-exec",
  "native": {
    "command": ["bin/pi05_server", "--checkpoint", "{checkpoint}"],
    "cwd": "bundle",                       // "bundle"（默认）| 绝对路径
    "transport": "stdio",                  // "stdio"（默认）| "http"
    "ready_timeout_sec": 120,              // 可选
    "shutdown_timeout_sec": 10,            // 可选
    "env": { "MY_FLAG": "1" }              // 可选的字面 env（不做占位符展开）
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `command` | 是 | argv 数组。除非绝对路径（或含 `/`），`argv[0]` 相对于 bundle 根解析。 |
| `cwd` | 否 | `bundle`（默认）= bundle 根。仅允许 `bundle` 或绝对路径。 |
| `transport` | 否 | `stdio`（默认）或 `http`。 |
| `ready_timeout_sec` | 否 | 就绪等待秒数，超时即失败（默认 120）。 |
| `shutdown_timeout_sec` | 否 | SIGTERM 后到 SIGKILL 的宽限（默认 10）。 |
| `env` | 否 | 字面附加环境变量；此处**不**展开占位符。 |

**占位符**可出现在 `command` 参数中：`{checkpoint}`、`{bundle_root}`、`{models_dir}`、`{variant}`、`{preset}`、`{extra:<key>}`。

### 6.2 stdio 传输

stdin/stdout 上的 NDJSON，UTF-8，每行一个 JSON 对象，行内不含换行。stderr 是日志（绝不承载协议）。

请求：`{"v":1,"id":<int>,"op":"run"|"health"|"shutdown","payload":{...}}`
应答：`{"v":1,"id":<int>,"ok":true,"payload":{...}}` 或 `{"v":1,"id":<int>,"ok":false,"error":{"code":<int>,"message":<str>}}`
就绪：进程在开始服务前输出 `{"v":1,"op":"ready","payload":{...}}`。`health` 必须在 `ready_timeout_sec` 内应答。

### 6.3 http 传输

进程绑定一个端点（host/port 由 host 选定，经 env 或 `command` 占位符传入），并向 stdout 输出就绪行 `{"v":1,"op":"ready","payload":{"endpoint":"<url>"}}`。host：

- **run**：`POST /run` 发送 run payload，读取响应，然后 `shutdown`。
- **serve**：监管进程（spawn → 就绪 → 保活 → 收到 SIGINT/SIGTERM 优雅停止）并把端点交给用户。host **不做**反向代理，客户端直连 bundle 进程的端点。（stdio 的 `serve` 未实现。）

### 6.4 生命周期

1. 以共享 env（§4）+ 字面 `env`、`cwd` 启动。
2. 等待就绪；超时则终止并失败。
3. 驱动 `run`（一次或多次请求）或 `serve`（直到被中断）。
4. 停止时：发送 `shutdown`（stdio）或 SIGTERM（http）；等待 `shutdown_timeout_sec`；必要时 SIGKILL。
5. 就绪前非零退出即 bundle 错误。

---

## 7. `native-abi` backend

host `dlopen` 一个模型运行时共享库并在**进程内**驱动。这是**库**通道：微秒级调用延迟与活状态 snapshot/restore，代价是共享地址空间与更严的 ABI 耦合。它复用被 FlashRT-Nexus 采纳的 FlashRT `frt_model_runtime_v1` face。

### 7.1 原生 spec

```jsonc
"entry": {
  "kind": "native-abi",
  "native": {
    "library": "{runtime_dir}/substrate/libflashrt_cpp_pi05_c-*.so",
    "open_symbol": "frt_model_runtime_open_v1",   // 默认
    "preload": [
      "{runtime_dir}/substrate/libflashrt_exec-*.so",
      "{runtime_dir}/substrate/libcapsule_nexus_flashrt-*.so"
    ],
    "config": { "precision": "{option:precision}" }
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `library` | 是 | 模型运行时 `.so`；glob 必须唯一匹配。允许占位符；`{runtime_dir}` = 选中的 `runtime/<env-key>/`。 |
| `open_symbol` | 否 | 工厂符号；默认 `frt_model_runtime_open_v1`。 |
| `preload` | 否 | 有序共享库列表，在 `library` **之前**以 `RTLD_GLOBAL` 加载。每项 glob 唯一匹配。 |
| `config` | 否 | 序列化为 JSON 并作为 `config_json` 传给 `open_symbol` 的对象。允许占位符，尤其是来自 `run_options`/`serve_options` 的 `{option:<name>}`。 |

### 7.2 工厂契约

`library` 必须精确导出 `FRT_MODEL_RUNTIME_OPEN_V1_SYMBOL`（`"frt_model_runtime_open_v1"`）：

```c
typedef int (*frt_model_runtime_open_v1_fn)(const char* config_json,
                                            frt_model_runtime_v1** out);
```

成功返回 `0` 和一个**已 retain** 的对象。host 通过对象的 `release(owner)` 精确释放一次。

### 7.3 ABI 前缀规则（只增不改）

host 读取返回的 `frt_model_runtime_v1`：

1. `abi_version` 必须等于 host 的 `FRT_MODEL_RUNTIME_ABI_VERSION`（即 manifest 的 `runtime_abi_version`）。
2. `struct_size` 必须 `>= FRT_MODEL_RUNTIME_V1_BASE_SIZE`（锚定 v1 基线最后一个字段 `release`）。
3. 仅在探测 `struct_size >= FRT_MODEL_RUNTIME_V1_QUERY_EXTENSION_SIZE` 后，才可读取 additive tail（`query_extension`）；绝不可假定 `sizeof`。
4. 原样的"热契约"：在 replay 之间更新 SWAP/STAGED 端口，不得重捕获、分配或重绑（见 `capsule/model_runtime.h`）。

### 7.4 驱动面

host 通过 **capsule** face（`FlashRT-Nexus/host/include/capsule/model_runtime.h`）驱动被采纳的运行时，而非原始 producer 结构体：

- ports：`cap_model_n_ports`、`cap_model_port_*`、`cap_model_set_input`、`cap_model_get_output`、`cap_model_find_port`
- execution：`cap_model_tick`、`cap_model_fire`、`cap_model_execute_stage`
- state：`cap_model_state_status`、`cap_model_snapshot`、`cap_model_restore`、`cap_model_restore_into`
- identity：`cap_model_fingerprint`、`cap_model_identity`

`snapshot`/`restore` 映射到 `flashcli serve` 的 session 端点；OPAQUE/step-only 运行时失败关闭（fail closed），绝不伪造 snapshot 语义。

### 7.5 单一 SONAME 约束

一个进程**只能**加载一个 `libflashrt_exec`（`libflashrt_exec.so.1`）。host 必须：

1. 按序以 `RTLD_GLOBAL` 加载 `preload` 项。
2. 最后加载 `library`。
3. 拒绝在同一进程加载第二个 bundle 的 `libflashrt_exec`（硬错误，而非陈旧句柄）。

这也是 `native-abi` **每进程仅服务一个** bundle 的原因。多 bundle 调度是独立的进程级问题。

### 7.6 Nexus 内嵌 session 通道（`session_library`）

可选、只增字段：让 host 通过 FlashRT-Nexus 的内嵌 C session 驱动被采纳的运行时，而非直接调用原始 producer verbs —— 仍然是进程内、仍然无 Python：

```jsonc
"native": {
  "library":         "{runtime_dir}/substrate/libflashrt_cpp_pi05_c-*.so",      // producer（open_symbol）
  "session_library": "{runtime_dir}/substrate/libcapsule_nexus_flashrt-*.so",   // Nexus host
  "loader_symbol":   "flashrt_loaded_model_open",   // 默认；一次调用完成加载+采纳
  "preload":         ["{runtime_dir}/substrate/libflashrt_exec-*.so"],
  "config": { "io": "native_v2", "checkpoint_path": "{checkpoint}", "...": "..." }
}
```

当存在 `session_library` 时，host：

1. 以 `RTLD_GLOBAL` 依序加载 `preload`，再加载 `session_library`；
2. 调用 `loader_symbol(provider_dso=library, config_json, &loader, &model)` 打开 producer DSO 并采纳其 `frt_model_runtime_v1`；
3. 在采纳的模型上开启常驻 `nexus_embedded_session`，驱动 `nexus_embedded_set_input` / `_tick` / `_get_output`，serve 场景再用 `_snapshot` / `_restore`。

端口按名寻址：`native.inputs`（`prompt` / `state` / `images`）与 `native.output_port`（默认 `actions`）。IMAGE 载荷为 `frt_image_view[]`（RGB8）；TEXT 为 UTF-8 字节；STATE/ACTION 为 f32。`config` 支持 §6.1 的占位符，外加 `{option:<name>}` 与 `{tokenizer}`。

`flashcli serve` 将 session 映射到 HTTP：
`GET /healthz`、`GET /v1/substrate`、`GET /v1/session/state`、
`POST /v1/session/snapshot`、`POST /v1/session/reset/{capsule}`，以及
`POST /v1/act`（兼容 `POST /v1/chat/completions`）。

校验：`session_library` 可选；存在时，若给了 `loader_symbol` 必须是 C 标识符。未声明 `session_library` 的 bundle 行为与 §7.4 完全一致。

---

## 8. manifest 校验规则

出现以下任一情况，bundle 非法：

- 存在 `kind`，但不属于 `python` / `native-exec` / `native-abi`。
- `kind == "native-exec"` 且（缺 `command`、`transport` 不在 {stdio, http}、或 `exec_protocol_version` 缺失）。
- `kind == "native-abi"` 且（缺 `library`、`runtime_abi_version` 缺失/错误、或 `open_symbol` 不是合法 C 标识符）。
- 在没有匹配原生 kind 的情况下出现 `runtime_abi_version` / `exec_protocol_version`。
- 调用时 `command`/`library`/`preload` 的 glob 匹配到 0 个或 1 个以上文件。
- 混合 kind 时，某原生 capability 缺少自身或继承的原生 spec。
- 原生 bundle 同时声明了原生 Python 入口字段是允许的（忽略）；但 `python` capability 缺 `module`/`attr` 则非法。

校验向前兼容：**旧** host 遇到不认识的 `kind` 必须以"升级 flashcli"消息失败，绝不按 Python 执行。

---

## 9. Conformance 套件

`tests/conformance/` 为每种 kind 保存一个 fixture bundle，外加一个共享的、语言无关的 runner。每个 host 实现（今天的 Python，迁移后的 Go）必须通过同一矩阵，从而两个 host 不会漂移。

| Fixture | Kind | 证明的内容 |
|---------|------|-----------|
| `python_echo/` | `python` | 基线 engine/script 入口、选项接线、权重 env |
| `exec_echo/` | `native-exec` | 启动、就绪、NDJSON run、优雅关闭、env/占位符 |
| `abi_echo/` | `native-abi` | `dlopen` 顺序、`frt_model_runtime_open_v1`、ABI 前缀探测、tick/snapshot |

`abi_echo` fixture 附带一份极小的 C 源码，测试在有 C 编译器时编译（否则跳过）；`exec_echo` 使用仅依赖标准库的 stub 以保持可移植。各 fixture 声明相同的逻辑请求/响应形状，使单一 runner 能断言跨 kind 的语义等价。

---

## 10. 推出规则

- **只增不改。** 任何既有字段含义不变。没有 `entry.kind`、`runtime_abi_version`、`exec_protocol_version` 的 bundle 不受影响。
- **默认 Python。** 缺省 `kind` 的行为与今天完全一致。
- **失败关闭。** 未知 kind 与版本不匹配一律中止并提示升级。
- **发布标准**在后续修订中加入本章字段；在此之前，本文对原生 kind 具权威性。
