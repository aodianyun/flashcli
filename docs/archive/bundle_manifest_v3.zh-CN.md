# 旧版 manifest 格式（format_version 3）

<p align="right"><a href="bundle_manifest_v3.md">English</a> · <strong>简体中文</strong></p>

> **归档参考，不进入当前文档索引。**
>
> Host 仍可读取旧 FlashHub ref 的 `format_version: 3`，但**新 bundle 不得使用 v3**。
> 新 bundle 必须使用 [bundle_publish_standard.zh-CN.md](../bundle_publish_standard.zh-CN.md)
> 中的 v4 格式。本文件只保留历史约定。

## 1. 范围

v3 bundle 是一个目录，包含：

- `flashcli-bundle.json`
- `entry.kind` 为 `python` 时的 `run.py` / `serve.py`
- 可选的 `flash_rt/` Python 树
- `runtime/<env-key>/` 下的原生 `.so`

纯原生 v3 bundle 省略 Python entry 和 `flash_rt/`，C 库放在
`runtime/<env-key>/substrate/`。

## 2. 顶层 manifest

| 字段 | 含义 |
|---|---|
| `format` | `"flashcli-model-bundle"` |
| `format_version` | `3` |
| `protocol_version` | `1` |
| `name` | bundle 描述名 |
| `description` | 可选说明 |
| `entry` | `run` / `serve` entry |
| `runtime` | `env_key -> runtime/<env-key>/` 映射 |
| `python_abi` | Python entry 必填，三位数字，如 `"312"` |
| `python_dependencies` | Python entry 的 venv 依赖 |
| `weights` | 单 preset 的主权重来源 |
| `extra_weights` | 可选的附加权重来源 |
| `variants` | 可选的多 preset 定义，用 `@variant` 选择 |
| `run_options` / `serve_options` | 对应能力的 CLI 参数 |
| `env` | engine entry 运行前注入的环境变量 |
| `post_pull` | 权重下载后的可选 host hook |
| `runtime_abi_version` | `native-abi` entry 必填 |
| `exec_protocol_version` | `native-exec` entry 必填 |

### Entry

```json
"entry": {
  "run": {
    "module": "run",
    "attr": "RunEngine",
    "mode": "engine"
  },
  "serve": {
    "module": "serve",
    "attr": "ServeEngine",
    "mode": "engine"
  }
}
```

- `mode`：`engine`（默认）或 `script`。
- `kind`：`python`（默认）、`native-exec` 或 `native-abi`。
- `module` / `attr`：Python entry 的模块与类/可调用对象。

### Runtime map

```json
"runtime": {
  "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
  "sm120-cu130-linux-x86_64-py312": "runtime/sm120-cu130-linux-x86_64-py312"
}
```

env key 与本机环境匹配。v3 使用版本作用域的 bundle/权重缓存，**不支持** v4 的
environment fallback、共享 runtime 目录或 runtime 可选环境。

### Variants

v3 允许一个 repo 定义多个 preset：

```json
"variants": {
  "qwen3": {
    "weights": { "source": "huggingface", "repo": "org/qwen3" },
    "run_options": []
  },
  "qwen36": {
    "weights": { "source": "huggingface", "repo": "org/qwen36" },
    "run_options": []
  }
}
```

用户用 `@variant` 选择：

```bash
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3
```

v4 禁止 `variants`；不同模型发布为独立 bundle。

### 权重

```json
"weights": {
  "source": "modelscope",
  "repo": "org/model",
  "revision": "master"
}
```

v3 允许 branch/tag，并将权重放在版本作用域缓存。v4 要求不可变完整 commit，
并写入按 source/repo/revision 共享的 store。

### Python 依赖

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": ["numpy", "safetensors", "transformers"]
}
```

v3 根据 `python_abi` 和这些依赖创建 bundle venv。纯原生 bundle 两者都省略。

## 3. 发布与兼容说明

- 只要 host 仍兼容，已有 v3 ref 可以继续使用。
- 不要原地修改已发布 v3 ref；新版本应发布为新的 v4 bundle/ref。
- 新 v4 bundle 不得写回 v3 字段（`variants`、顶层 `runtime`、`@variant`）。
- 当前编写、运行时与发布规范：[bundle_publish_standard.zh-CN.md](../bundle_publish_standard.zh-CN.md)。
