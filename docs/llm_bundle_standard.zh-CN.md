# LLM 类模型 Bundle 打包规范（OpenAI + Anthropic 统一服务）

> 适用：FlashRT 适配的大语言模型（LLM）以 flashcli bundle（format_version 4）发布到 FlashHub。
> 本文是 [flashcli Model Bundle 发布标准](https://github.com/aodianyun/flashcli/blob/main/docs/bundle_publish_standard.zh-CN.md)
> 在 **LLM 服务（`flashcli serve`）** 方面的补充规则：通用的目录、manifest、`.so` 命名、
> 权重、溯源等要求仍以发布标准为准，本文只规定 LLM bundle 额外必须满足的内容。

参考实现（均已按本规范发布并实测）：

| 模型 | FlashHub 引用 | 说明 |
| --- | --- | --- |
| Spark-X2.6-4B | `xym/spark_x26_4b:1.0.7` | 参考实现；RTX 3060 / 4060 Ti / 5060 Ti + 天数 MR-V100 |
| Spark-X2.6-1.7B | `xym/spark_x26_1p7b:1.0.1` | 按本规范移植的第二个模型（胶水差异 < 100 行） |

---

## 目录

1. 目标与总体要求
2. 架构：协议层 `llm_serve` 与模型胶水
3. 发布目录结构
4. manifest（`flashcli-bundle.json`）规则
5. 胶水接口：`ModelAdapter` 契约（完整代码）
6. 入口：`serve.py` / `run.py`（完整代码）
7. 胶水模板：`_model_engine.py`（完整代码）
8. 工具调用格式与推理格式的选择
9. 流式实现与参考驱动（完整代码）
10. 服务端行为规则（必须一致）
11. 接口清单与调用示例
12. 测试与验收
13. 打包、发布与版本
14. 常见问题
附录 A. `llm_serve` 模块说明与获取方式
附录 B. 数据类型（完整代码）
附录 C. `LLMServeEngine`（flashcli 入口基类，完整代码）

---

## 1. 目标与总体要求

一个 LLM bundle 的 `flashcli serve` **必须**：

1. 同时提供 **OpenAI 兼容**（`/v1/chat/completions`、`/v1/responses`、`/v1/completions`、
   `/v1/models`）与 **Anthropic 兼容**（`/v1/messages`、`/v1/messages/count_tokens`）接口；
2. 支持流式（SSE）、工具调用（含并行、`tool_choice`）、推理通道（thinking）、图片输入处理、
   API key 鉴权、并发排队；可直接配置给 Claude Code、opencode、OpenAI Agents SDK 等智能体；
3. 使用 **engine 模式** 的 `ServeEngine`，监听地址与端口由 flashcli host 的 `--host` /
   `--port` 提供；
4. 复用统一协议层 `llm_serve/`（不按模型修改），模型差异只写在"胶水"里；
5. 通过第 12 节的验收测试后再发布。

用户侧的使用方式因此对所有 LLM bundle 一致：

```bash
flashcli serve <org>/<name>:<version> --host 0.0.0.0 --port 8080 --api-key <key>
# OpenAI 兼容：  base_url = http://<host>:8080/v1
# Anthropic 兼容：base_url = http://<host>:8080
```

## 2. 架构：协议层 `llm_serve` 与模型胶水

```text
                 flashcli serve <ref> --host H --port P [--api-key K ...]
                                   │  （engine 模式：host 建 FastAPI app、监听端口）
                                   ▼
 ┌──────────────── llm_serve/（所有 LLM bundle 共用，原样复制，禁止按模型修改）────────────┐
 │ openai_api.py     /v1/chat/completions  /v1/responses  /v1/completions               │
 │ anthropic_api.py  /v1/messages  /v1/messages/count_tokens                             │
 │ server.py         路由、鉴权、/v1/models、/health、LLMServeEngine（flashcli 入口基类）│
 │ engine.py         单 GPU FIFO 队列、取消、推理预算、采样默认值                          │
 │                   增量 detokenize → stop 字符串 → <think> 拆分 → 工具调用解析           │
 │ parsers.py        推理通道与工具调用格式（glm45 / hermes / qwen3_coder）                │
 │ datatypes.py  media.py  adapter.py  debug.py                                           │
 └───────────────────────────────────┬────────────────────────────────────────────────────┘
                                     │ ModelAdapter（胶水契约，第 5 节）
 ┌───────────────────────────────────▼──────────────────── 每个模型自己写 ──────────────┐
 │ _<model>_engine.py   load / render(chat template) / generate(按块 yield token ids)     │
 │                      decode / encode / is_end_token；声明 tool_parser 等               │
 │ serve.py             三行：class ServeEngine(LLMServeEngine): adapter_factory = …      │
 │ run.py               flashcli run 入口（复用同一胶水）                                  │
 └──────────────────────────────────────────────────────────────────────────────────────┘
```

规则：

- `llm_serve/` 只依赖 `fastapi` / `uvicorn` / `pydantic`，不依赖 torch；所有协议、流式、解析、
  调度逻辑只在这里维护。需要改协议层时改参考实现并同步到所有 LLM bundle，保持一致。
- 胶水不处理 HTTP、JSON、SSE、鉴权、排队；协议层不认识任何具体模型。

## 3. 发布目录结构

```text
<bundle>/                         # 发布根（dist/）
├── flashcli-bundle.json          # manifest（第 4 节）
├── serve.py                      # flashcli serve 入口（ServeEngine，engine 模式）
├── run.py                        # flashcli run 入口（RunEngine，engine 模式）
├── _<model>_engine.py            # 胶水（第 5、7 节）
├── llm_serve/                    # 协议层（附录 A），原样复制
│   ├── __init__.py  adapter.py  anthropic_api.py  datatypes.py  debug.py
│   └── engine.py  media.py  openai_api.py  parsers.py  server.py
├── flash_rt/                     # entry 可达的 FlashRT Python 模块（无 .so）
├── runtime/<env>/*.so            # 每个 environment 的原生库
└── README.md  LICENSE  NOTICE
```

- 发布树必须最小：本规范文档、测试脚本、`.gitignore`、缓存不进 `dist/`。
- 不要把模块命名为 `types.py` 等与标准库重名的名字（会遮蔽 stdlib，导致导入失败）。

## 4. manifest（`flashcli-bundle.json`）规则

### 4.1 entry：serve 必须是 engine 模式

```json
"entry": {
  "run":   {"kind": "python", "module": "run",   "attr": "RunEngine",   "mode": "engine"},
  "serve": {
    "kind": "python", "module": "serve", "attr": "ServeEngine", "mode": "engine",
    "capabilities": [
      "openai.chat", "openai.responses", "openai.completions",
      "anthropic.messages", "anthropic.count_tokens"
    ]
  }
}
```

- 监听地址/端口由 host 的 `--host`（默认 `0.0.0.0`）/ `--port`（默认 `8000`）提供；
  **禁止**在 `serve_options` 中声明 `ip` / `host` / `port`。
- host 会先调用 `ServeEngine.register_routes(app)` 再挂自带路由，`llm_serve` 的路由优先。
- `serve.capabilities` 声明由 host 启用的协议路由；缺省等价于 `["openai.chat"]`，显式 `[]` 只保留 `/health`、`/v1/models`。当前 host 已内置 `openai.chat`、`openai.completions`、`openai.responses`、`openai.embeddings`、`openai.moderations`、`openai.audio.*`、`openai.images.*`、`openai.videos`、`anthropic.messages`、`anthropic.count_tokens`（需要 engine 提供 `count_tokens`，否则返回 `501`）和 `anthropic.models`。其他已声明但 host 尚未实现的 HTTP 能力返回 `501`，随后按 host 模块落地进度补齐，或由 bundle 通过 `register_routes` 提供。
- `anthropic.count_tokens` 需要 `ServeEngine.count_tokens(request) -> int`（可返回 awaitable）；缺失时该端点明确返回 `501`。
- `openai.embeddings` 需要 `ServeEngine.embed(request: EmbeddingRequest) -> EmbeddingResult`（可返回 awaitable）；缺失时返回 `501`。
- `openai.audio.*` 需要 `ServeEngine.transcribe(request: AudioTranscriptionRequest) -> AudioTranscriptionResult` 和 `ServeEngine.speech(request: SpeechRequest) -> SpeechResult`；缺失时返回 `501`。
- `openai.images.*` 需要 `ServeEngine.generate_images(request: ImageGenerationRequest) -> ImageGenerationResult`；缺失时返回 `501`。
- `openai.moderations` 需要 `ServeEngine.moderate(request: ModerationRequest) -> ModerationResult`；缺失时返回 `501`。
- `openai.videos` 需要 `ServeEngine.create_video/get_video/download_video/delete_video`；缺失时返回 `501`。
- **禁止** script 模式自起 uvicorn（参数、帮助、日志、venv 行为会与其它 bundle 不一致）。

### 4.2 依赖

```json
"python_dependencies": {
  "torch": {"package": "torch==2.14.1", "index": "cu130"},
  "pip": ["numpy==2.5.4", "transformers==5.20.2", "safetensors==0.8.0",
          "fastapi==0.162.0", "uvicorn==0.54.0", "pydantic==2.14.1"]
}
```

协议层只需 `fastapi` / `uvicorn` / `pydantic`；`transformers` 用于 tokenizer 与 chat
template。版本必须固定。

### 4.3 统一的 serve_options（所有 LLM bundle 必须提供，名字与语义一致）

```json
[
  {"name": "model_name", "type": "string", "default": "<model-id>", "phase": "load",
   "help": "Model id reported by /v1/models and in responses (requests may name any model)."},
  {"name": "api_key", "type": "string", "default": "", "phase": "load",
   "help": "Require this key as 'Authorization: Bearer <key>' or 'x-api-key: <key>' (empty: no auth)."},
  {"name": "default_max_tokens", "type": "integer", "default": 8192, "phase": "load",
   "help": "max_tokens for OpenAI requests that omit it (always capped by the context left)."},
  {"name": "enable_thinking", "type": "boolean", "default": true, "phase": "load",
   "help": "Default for the reasoning channel when a request does not choose."},
  {"name": "max_thinking_tokens", "type": "integer", "default": 8192, "phase": "load",
   "help": "Reasoning tokens before the server closes the thinking channel and lets the model answer (requests may set a budget; reasoning_effort=low caps it at 2048; 0 disables)."},
  {"name": "tool_temperature", "type": "float", "default": 0.0, "phase": "load",
   "help": "Temperature for requests that carry tools and set none (0 = greedy; negative = the model's default sampling)."},
  {"name": "image_input", "type": "string", "default": "placeholder", "phase": "load",
   "help": "Image parts on a text-only model: placeholder (replace with a note) | reject (HTTP 400)."},
  {"name": "max_queue", "type": "integer", "default": 32, "phase": "load",
   "help": "Requests allowed to wait for the GPU (batch 1, FIFO); beyond it the server answers 503."},
  {"name": "max_seq", "type": "integer", "default": 32768, "phase": "load",
   "help": "KV/context budget in tokens (prompt + generation)."},
  {"name": "prefill_cap", "type": "integer", "default": 32768, "phase": "load",
   "help": "Largest prompt accepted by the request path."},
  {"name": "warmup", "type": "string", "default": "", "phase": "warmup",
   "help": "Capture graphs before serving: prompt_tokens:new_tokens[,..]."}
]
```

- 模型专有参数（例如 `spec_rows`、`kv_dtype`、`weight_route`、`stream_chunk`、
  `first_token_from_decode`）接在后面，由胶水 `load(**options)` 读取。
- `max_seq` / `prefill_cap` 在加载时分配 KV，只能启动时设置；serve 默认 32k（智能体的
  系统提示 + 工具定义约 11k token），需要更长时两者一起调大（如 131072）。
- `run_options` 按 flashcli 发布标准声明（`prompt`、`max_tokens`、`temperature`、`top_p`、
  `seed`、`enable_thinking` + 模型加载参数）。

## 5. 胶水接口：`ModelAdapter` 契约（完整代码）

`llm_serve/adapter.py`（协议层的一部分，原样复制）：

```python
"""The glue contract: what one model has to provide to be served.

A model bundle implements ``ModelAdapter`` (load weights, render a
``ChatRequest`` into prompt ids, yield generated ids in chunks, decode ids)
and picks a reasoning and a tool-call parser. Everything else -- both HTTP
dialects, streaming, stop strings, tool-call extraction, queueing, auth --
lives in ``llm_serve`` and is the same for every model.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Iterator

from .datatypes import ChatRequest


@dataclass
class Prompt:
    """A rendered request, ready for ``ModelAdapter.generate``."""

    ids: list[int]
    #: generation starts inside the reasoning block (template opened it)
    reasoning_open: bool = False
    #: text the template already emitted for the assistant (forced tool call);
    #: fed to the parsers ahead of the generated text, never re-sent to clients
    #: as-is
    forced_prefix: str = ""
    #: tool names the template rendered (for argument typing in the parser)
    tool_schemas: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class SamplingParams:
    max_tokens: int
    temperature: float = 0.0          # 0 = greedy
    top_p: float = 1.0
    top_k: int = 0                    # 0 = off
    seed: int | None = None


class ModelAdapter:
    """Base class for a model glue. Override the ``NotImplementedError`` parts.

    Class attributes describe the model to the protocol layer:

    * ``model_id`` -- id reported by ``/v1/models`` and responses.
    * ``supports_vision`` -- images reach ``render``; otherwise the server
      applies ``image_policy`` (placeholder text or a 400).
    * ``reasoning_parser`` / ``tool_parser`` -- names registered in
      ``llm_serve.parsers`` (``"think"``, ``"glm45"``, ``"hermes"``,
      ``"qwen3_coder"``), or ``None`` when the model has no such channel.
    * ``context_length`` / ``max_prompt_tokens`` -- request limits.
    """

    model_id: str = "model"
    supports_vision: bool = False
    supports_tools: bool = True
    reasoning_parser: str | None = None
    tool_parser: str | None = None
    context_length: int = 4096
    max_prompt_tokens: int = 4096
    default_enable_thinking: bool = True
    default_temperature: float = 0.0
    default_top_p: float = 1.0

    # ── lifecycle ───────────────────────────────────────────────────────
    def load(self, checkpoint: str, **options: Any) -> None:
        raise NotImplementedError

    def warmup(self, spec: str | None) -> None:
        """Optional: capture graphs / compile ahead of the first request."""

    # ── prompt ──────────────────────────────────────────────────────────
    def render(self, request: ChatRequest) -> Prompt:
        raise NotImplementedError

    def count_tokens(self, request: ChatRequest) -> int:
        return len(self.render(request).ids)

    # ── generation ──────────────────────────────────────────────────────
    def generate(self, prompt: Prompt, params: SamplingParams,
                 cancel: threading.Event) -> Iterator[list[int]]:
        """Yield the generated ids in order, a chunk at a time.

        Stop as soon as an end-of-turn id is produced (it may be included) or
        ``cancel`` is set. Called on the single GPU worker thread.
        """
        raise NotImplementedError

    def decode(self, ids: list[int]) -> str:
        raise NotImplementedError

    def encode(self, text: str) -> list[int]:
        """Optional: text -> ids without special-token handling. Enables the
        reasoning budget (the server closes the thinking channel by appending
        the encoded end tag and continuing)."""
        raise NotImplementedError

    def is_end_token(self, token_id: int) -> bool:
        raise NotImplementedError

    def info(self) -> dict[str, Any]:
        """Extra fields for ``/health``."""
        return {}
```

### 5.1 成员说明

| 成员 | 必须 | 说明 |
| --- | --- | --- |
| `model_id` | 是 | `/v1/models` 与响应中的 id；`load` 时取 `options["model_name"]` |
| `context_length` / `max_prompt_tokens` | 是 | 上下文总长度与最长 prompt（按 KV 分配设置） |
| `tool_parser` | 是 | `"glm45"` / `"hermes"` / `"qwen3_coder"` / `None`（第 8 节） |
| `reasoning_parser` | 是 | `"think"`（模板有 `<think>…</think>`）或 `None` |
| `supports_tools` / `supports_vision` | 是 | 能力声明；`supports_vision=False` 时图片按 `image_input` 处理，不会进 `render` |
| `default_enable_thinking` | 否 | 模板默认是否开推理 |
| `default_temperature` / `default_top_p` | 建议 | 不带工具、未指定采样的请求使用；取 `generation_config.json` |
| `load(checkpoint, **options)` | 是 | 加载一次、常驻显存 |
| `warmup(spec)` | 否 | 预捕获图 |
| `render(request) -> Prompt` | 是 | 按 checkpoint 的 chat template 渲染并分词 |
| `generate(prompt, params, cancel)` | 是 | 按块 yield 新 token id；遇结束符或 `cancel` 置位就停（第 9 节） |
| `decode(ids)` | 是 | `skip_special_tokens=True`；`<think>`、`<tool_call>` 等非 special 标签必须保留 |
| `encode(text)` | 必须 | 不加特殊符号分词；实现后才启用推理预算（第 10 节） |
| `is_end_token(id)` | 是 | EOS 与模板的轮次结束符（如 `<\|im_end\|>`） |
| `info()` | 否 | 附加到 `/health` |

### 5.2 `render` 的要求

1. `request.messages` 已统一为 `system / user / assistant / tool` 四种角色（OpenAI `developer`、
   Anthropic `system` 轮 / `tool_result` / `tool_use` / `thinking`、Responses
   `function_call` / `function_call_output` / `reasoning` 都已映射），转成模板需要的 dict：
   assistant 的 `reasoning_content`、`tool_calls`（`arguments` 按模板要求给 dict 或 JSON 字符串），
   tool 消息的 `content`。
2. `tokenizer.apply_chat_template(chat, tools=[t.as_openai() ...], add_generation_prompt=True,
   enable_thinking=..., **request.extras.get("chat_template_kwargs", {}))`。
3. **必须**在结果后原样拼接 `request.extras["assistant_prefix"]`（强制工具调用、助手预填用），
   再以 `add_special_tokens=False` 分词。
4. `Prompt.reasoning_open`：生成提示已打开 `<think>` 时为 True；有 `assistant_prefix` 时为 False。

## 6. 入口：`serve.py` / `run.py`（完整代码）

`serve.py`（所有 LLM bundle 都是这几行，只改导入的胶水类名）：

```python
"""``flashcli serve`` entry (engine mode): <Model> behind OpenAI- and
Anthropic-compatible HTTP APIs. The host owns --host/--port; llm_serve mounts
the routes; the model glue is ``_model_engine.ModelAdapter_``."""

from __future__ import annotations

from llm_serve.server import LLMServeEngine

from _model_engine import ModelAdapter_


class ServeEngine(LLMServeEngine):
    adapter_factory = ModelAdapter_
```

`run.py`（复用同一胶水；模型有定长测速等需求时在此扩展）：

```python
"""``flashcli run`` entry: one prompt in, one answer out (same glue as serve)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from llm_serve.adapter import SamplingParams
from llm_serve.datatypes import ChatRequest, Message, TextPart

from _model_engine import ModelAdapter_


class RunEngine:
    def __init__(self) -> None:
        self._adapter = ModelAdapter_()

    def load(self, checkpoint: Path, preset: Any, **options: Any) -> None:
        del preset
        self._adapter.load(str(checkpoint), **options)

    def predict(self, *, prompt: str = "", images: list[Any] | None = None,
                **kwargs: Any) -> dict[str, Any]:
        del images
        a = self._adapter
        req = ChatRequest(messages=[Message("user", [TextPart(prompt)])],
                          enable_thinking=bool(kwargs.get("enable_thinking", True)))
        p = a.render(req)
        params = SamplingParams(max_tokens=int(kwargs.get("max_tokens", 256)),
                                temperature=float(kwargs.get("temperature", 0.0)),
                                top_p=float(kwargs.get("top_p", 1.0)),
                                seed=kwargs.get("seed"))
        new: list[int] = []
        t0 = time.perf_counter()
        for chunk in a.generate(p, params, threading.Event()):
            cut = next((i for i, t in enumerate(chunk) if a.is_end_token(t)), None)
            new.extend(chunk if cut is None else chunk[:cut])
            if cut is not None:
                break
        wall = time.perf_counter() - t0
        text = a.decode(new)
        if kwargs.get("echo", True):
            print(text)
        return {"text": text, "usage": {"prompt_tokens": len(p.ids), "completion_tokens": len(new),
                                        "wall_s": round(wall, 4)}}
```

## 7. 胶水模板：`_model_engine.py`（完整代码）

复制为 bundle 根下的 `_<model>_engine.py`，按标注的 4 处修改（模型 id、frontend 构造、
工具/推理格式、加载参数）。基于 FlashRT LLM frontend 的通用接口（`tokenizer`、
`eos_token_id`、`generate_request`），开箱即为完整可用的服务（流式为一次性返回；
逐 token 流式见第 9 节）。该模板已在 Spark-X2.6-4B 上只改标注处端到端实测通过
（聊天、推理拆分、工具调用与结果回填、流式、Anthropic）。

```python
"""<Model> glue for llm_serve (template).

Copy to the bundle root as ``_<model>_engine.py`` and fill in the four
marked places (MODEL ID, FRONTEND, TOOL / REASONING FORMAT, load options).
Everything protocol-related (OpenAI / Anthropic endpoints, streaming, tool
calls, reasoning split, stop strings, queueing, auth) is in ``llm_serve`` and
is not touched per model.

The template drives the common FlashRT LLM frontend surface:

    fe = Frontend(checkpoint, **load_options)
    fe.tokenizer                         # HF tokenizer with a chat template
    fe.eos_token_id                      # int | None
    fe.generate_request(ids, max_new_tokens=..., do_sample=..., temperature=...,
                        top_p=..., seed=...) -> prompt + new ids (stops at EOS)

That gives a correct, complete server whose stream arrives in one piece. For
token streaming, replace ``generate`` with a chunked driver (see
``STREAMING`` below and the Spark example in ``_spark_engine.py``).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterator

from llm_serve.adapter import ModelAdapter, Prompt, SamplingParams
from llm_serve.datatypes import ChatRequest, ImagePart, TextPart

# ── 1. MODEL ID ──────────────────────────────────────────────────────────
DEFAULT_MODEL_ID = "my-model"          # what /v1/models reports
DEFAULT_MAX_SEQ = 32768


# ── 2. FRONTEND ──────────────────────────────────────────────────────────
def build_frontend(checkpoint: str, options: dict[str, Any]) -> Any:
    """Construct the FlashRT frontend once; the server keeps it resident."""
    from flash_rt.frontends.torch.my_model import MyModelFrontend   # <- change
    return MyModelFrontend(
        checkpoint,
        max_seq=int(options.get("max_seq") or DEFAULT_MAX_SEQ),
        device=str(options.get("device") or "cuda"),
    )


def _text(parts: list[Any]) -> str:
    return "".join(p.text if isinstance(p, TextPart) else "[image]"
                   for p in parts if isinstance(p, (TextPart, ImagePart)))


class ModelAdapter_(ModelAdapter):
    # ── 3. TOOL / REASONING FORMAT (read the checkpoint's chat template) ──
    #: "glm45" | "hermes" | "qwen3_coder" | None (see llm_serve/parsers.py)
    tool_parser = "hermes"
    #: "think" when the template has a <think>...</think> channel, else None
    reasoning_parser = "think"
    supports_tools = True
    supports_vision = False            # True only if render() handles ImagePart
    default_enable_thinking = True

    def __init__(self) -> None:
        self.model_id = DEFAULT_MODEL_ID
        self.fe: Any = None
        self.tokenizer: Any = None
        self._end_ids: set[int] = set()

    # ── lifecycle ───────────────────────────────────────────────────────
    def load(self, checkpoint: str, **options: Any) -> None:
        if self.fe is not None:
            return
        ckpt = str(Path(checkpoint).expanduser().resolve())
        self.model_id = str(options.get("model_name") or DEFAULT_MODEL_ID)
        self.fe = build_frontend(ckpt, options)
        self.tokenizer = self.fe.tokenizer
        self.context_length = int(options.get("max_seq") or DEFAULT_MAX_SEQ)
        self.max_prompt_tokens = int(options.get("prefill_cap") or self.context_length)
        eos = getattr(self.fe, "eos_token_id", None)
        self._end_ids = {int(eos)} if eos is not None else set()
        # also stop on the template's end-of-turn token if it differs from EOS
        for tok in ("<|im_end|>", "<|endoftext|>"):            # <- adjust per model
            tid = self.tokenizer.convert_tokens_to_ids(tok)
            if isinstance(tid, int) and tid != self.tokenizer.unk_token_id:
                self._end_ids.add(tid)
        # 4. sampling defaults for requests that choose none: the checkpoint's
        # recommendation (requests with tools decode greedily, see llm_serve)
        gen = Path(ckpt) / "generation_config.json"
        if gen.is_file():
            cfg = json.loads(gen.read_text(encoding="utf-8"))
            if cfg.get("do_sample", True):
                self.default_temperature = float(cfg.get("temperature", 1.0))
                self.default_top_p = float(cfg.get("top_p", 1.0))

    def warmup(self, spec: str | None) -> None:
        """``prompt_tokens:new_tokens[,...]``: run synthetic requests."""
        for item in str(spec or "").split(","):
            left, _, right = item.strip().partition(":")
            if left:
                ids = [100] * max(1, int(left))
                for _ in self.generate(Prompt(ids=ids), SamplingParams(max_tokens=int(right or 16)),
                                       threading.Event()):
                    pass

    # ── prompt ──────────────────────────────────────────────────────────
    def render(self, request: ChatRequest) -> Prompt:
        chat: list[dict[str, Any]] = []
        for m in request.messages:
            msg: dict[str, Any] = {"role": m.role, "content": _text(m.parts)}
            if m.role == "assistant":
                if m.reasoning:
                    msg["reasoning_content"] = m.reasoning
                if m.tool_calls:
                    msg["tool_calls"] = [{"id": c.id, "type": "function",
                                          "function": {"name": c.name, "arguments": c.arguments}}
                                         for c in m.tool_calls]
            if m.role == "tool" and m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            chat.append(msg)
        kwargs = dict(request.extras.get("chat_template_kwargs") or {})
        kwargs["enable_thinking"] = bool(request.enable_thinking)
        text = self.tokenizer.apply_chat_template(
            chat, tools=[t.as_openai() for t in request.tools] or None,
            tokenize=False, add_generation_prompt=True, **kwargs)
        prefix = str(request.extras.get("assistant_prefix") or "")
        ids = self.tokenizer(text + prefix, add_special_tokens=False)["input_ids"]
        # True when the generation prompt already opened <think>; check the
        # template: some open it themselves, some leave it to the model
        opened = text.rstrip().endswith("<think>")
        return Prompt(ids=list(ids), reasoning_open=opened and not prefix)

    # ── generation ──────────────────────────────────────────────────────
    def generate(self, prompt: Prompt, params: SamplingParams,
                 cancel: threading.Event) -> Iterator[list[int]]:
        """Non-streaming baseline: one whole-request call, one chunk.

        STREAMING: yield ids every few tokens instead (llm_serve stops at the
        first end id and on ``cancel``). With a FlashRT whole-request decode
        graph, relaunch it in chunks the way ``SparkStreamer`` does.
        """
        import torch

        ids = torch.tensor(prompt.ids, dtype=torch.int64)
        sample = params.temperature > 0
        with torch.no_grad():
            out = self.fe.generate_request(
                ids, max_new_tokens=int(params.max_tokens), do_sample=sample,
                temperature=params.temperature if sample else 1.0,
                top_p=params.top_p if sample else 1.0, seed=params.seed)
        yield [int(t) for t in out[len(prompt.ids):].tolist()]

    def decode(self, ids: list[int]) -> str:
        return self.tokenizer.decode(ids, skip_special_tokens=True)

    def encode(self, text: str) -> list[int]:
        # enables the reasoning budget (closing </think> for the model)
        return list(self.tokenizer(text, add_special_tokens=False)["input_ids"])

    def is_end_token(self, token_id: int) -> bool:
        return token_id in self._end_ids

    def info(self) -> dict[str, Any]:
        return {"context_length": self.context_length}
```

## 8. 工具调用格式与推理格式的选择

打开 checkpoint 的 `chat_template.jinja`（或 `tokenizer_config.json` 的 `chat_template`），
看 assistant 的 `tool_calls` 如何渲染：

| 模板里的工具调用 | `tool_parser` | 典型模型 |
| --- | --- | --- |
| `<tool_call>NAME<arg_key>K</arg_key><arg_value>V</arg_value></tool_call>` | `glm45` | Spark-X2.x、GLM-4.5/4.6 |
| `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` | `hermes` | Qwen2.5、Qwen3、Hermes |
| `<tool_call><function=NAME><parameter=K>V</parameter></function></tool_call>` | `qwen3_coder` | Qwen3-Coder、Qwen3.5+/3.6 |

- 模板有 `<think>…</think>` → `reasoning_parser = "think"`。
- 用 tokenizer 确认这些标签为 **非 special token**（`skip_special_tokens=True` 解码后仍在）；
  否则 `decode` 需改用 `skip_special_tokens=False` 并自行去掉 EOS。
- 结束符除 EOS 外还要包含模板的轮次结束 token。
- 新格式：在 `llm_serve/parsers.py` 的 `TOOL_FORMATS` 增加一项（起止标签、解析函数、强制
  调用前缀），并在离线测试中覆盖"任意切分点"的流式解析；该改动回写参考实现并同步所有
  LLM bundle。

## 9. 流式实现与参考驱动（完整代码）

`generate` 每 yield 一块 id，协议层就解码并推给客户端；遇结束符或 `cancel`（客户端断开）
应尽快停止。实现方式按优先级：

1. **frontend 支持逐步/分块 decode**：每 8~16 个 token yield 一次。
2. **整请求 CUDA Graph（FlashRT 常见）**：把 decode 循环的终止位置放在设备内存，每块只
   把它抬高 N 再重放同一张图，读出这一块 token。**不改 kernel、复用原图**，与整段生成
   逐 token 一致，额外开销约 1%；遇到结束符即停（旧的整段图每个请求都要跑满 `max_tokens`）。
   **不要流水线化**（提前排下一块）：最后一块会在轮次结束后继续占 GPU，推迟下一个请求。
3. **只能一次生成**：一次 yield 全部 id（第 7 节模板默认）——可用但不推荐。

建议同时做：

- 加载时预捕获所有 key 桶的请求图，避免首个请求付捕获开销。
- **首个答案 token 走 decode 路径**：prefill 除最后一个 prompt token 外的全部，再把最后一个
  token 放回 decode 循环作为当前 token，由第一步 verify 产生首个答案 token。多行 prefill 的
  激活被量化（FP4 / INT8），decode 保持 bf16，实测首 token 与 bf16 原模型一致率
  4B 13/16 → 15/16、1.7B 11/16 → 12/16，TTFT 多约一次 decode 步（2–3 ms）。

参考驱动（Spark-X2.6，FlashRT 投机解码 while-graph；摘自 `_spark_engine.py`）：

```python
class SparkStreamer:
    """Chunked driver for the W4A16 runtime's request graphs."""

    def __init__(self, fe: Any, chunk: int, first_token_from_decode: bool = True) -> None:
        import torch

        self.fe = fe
        self.rt = fe.runtime
        self.chunk = max(1, int(chunk))
        # Draw the first answer token from the decode (verify) path rather than
        # the prefill's last row: on the multi-row prefill route activations
        # are quantised (FP4 MMA on SM120, INT8 on SM86 / SM89), the decode
        # GEMV keeps them bf16. First answer tokens vs HF bf16 on 16 one-word
        # prompts (5060 Ti): 4B 13/16 -> 15/16, 1.7B 11/16 -> 12/16.
        self.first_token_from_decode = bool(first_token_from_decode)
        self.streaming = bool(getattr(self.rt, "_spec_rows", 0))
        # pinned staging for the next ctl[1] (H2D) and a chunk's tokens (D2H)
        self._ctl = torch.zeros(1, dtype=torch.int32).pin_memory()
        self._tok = torch.zeros(0, dtype=torch.int64)
        self._ev = torch.cuda.Event()

    def _sampling(self, p: SamplingParams) -> None:
        import torch

        rt = self.rt
        if p.temperature and p.temperature > 0:
            rt.set_sampling((float(p.temperature), float(p.top_p), 0, 0))
            seed = int(torch.seed() if p.seed is None else p.seed) & ((1 << 63) - 1)
            rt.rng.copy_(torch.tensor([seed, 0, 0], dtype=torch.int64), non_blocking=False)
        else:
            rt.set_sampling(None)

    def _prefill(self, ids: Any, rows: int, first: int) -> None:
        """``generate_request``'s prefill half: ids in, prefill graph (captured
        on first sight of this length), first token drawn, ``ctl[1]`` set to
        ``rows + first - 1`` by the captured ``spec_begin``."""
        import torch

        rt = self.rt
        rt.ids_buf[:rows].copy_(ids, non_blocking=True)
        rt._req_n[0] = first
        rt.spec_ctl[5:6].copy_(rt._req_n, non_blocking=True)
        g = rt._prefill_graphs.get(rows)
        if g is not None:
            rt._prefill_graphs.move_to_end(rows)
            g.replay()
            return
        rt._prefill_request(rows)
        g = torch.cuda.CUDAGraph()
        s = rt._capture_stream or torch.cuda.Stream()
        rt._capture_stream = s
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            with torch.cuda.graph(g, stream=s):
                rt._prefill_request(rows)
        torch.cuda.current_stream().wait_stream(s)
        rt._prefill_graphs[rows] = g
        while len(rt._prefill_graphs) > rt._PREFILL_GRAPHS_MAX:
            rt._prefill_graphs.popitem(last=False)

    def generate(self, ids: Any, p: SamplingParams,
                 cancel: threading.Event) -> Iterator[list[int]]:
        import torch

        from flash_rt import flash_rt_sparkx25 as sk

        ids = ids.reshape(-1).to(torch.int64)
        rows, max_new = int(ids.numel()), int(p.max_tokens)
        self._sampling(p)
        if not self.streaming:
            # w4a4 route / spec_rows=0: one whole-request graph, no chunking
            with torch.no_grad():
                out = self.fe.generate_request(
                    ids, max_new_tokens=max_new, do_sample=p.temperature > 0,
                    temperature=p.temperature if p.temperature > 0 else 1.0,
                    top_p=p.top_p if p.temperature > 0 else 1.0, seed=p.seed)
            yield [int(t) for t in out[rows:].tolist()]
            return

        rt = self.rt
        stream = torch.cuda.current_stream()
        bucket = min(rt.max_seq, max(1024, 1 << (rows + max_new).bit_length()))
        with torch.no_grad():
            if bucket not in rt._request_graphs:
                rt._capture_spec_loop(bucket)
            rt._request_graphs.move_to_end(bucket)
            _, exe = rt._request_graphs[bucket]
            if self._tok.numel() < self.chunk:
                self._tok = torch.zeros(self.chunk, dtype=torch.int64).pin_memory()
            last = rows + max_new - 1               # position of the final token
            if self.first_token_from_decode and rows > 1:
                # Prefill all but the last prompt token, then put that token
                # back as the decode loop's current token (history slot and
                # verify row 0, where spec_begin placed the prefill's draw):
                # the first verify step predicts the first answer token.
                self._prefill(ids[:rows - 1], rows - 1, 1)
                tail = ids[rows - 1:rows]
                rt.hist[rows - 1:rows].copy_(tail, non_blocking=True)
                rt.spec_tok[0:1].copy_(tail, non_blocking=True)
                target, done = rows - 1, rows       # nothing produced yet
            else:
                self._prefill(ids, rows, 1)         # chunk 0: the prefill's token
                target, done = rows, rows           # ctl[1]; hist[rows:done] sent
            if hasattr(rt, "_sage_kept_reset"):
                rt._sage_kept_reset()               # as generate_request does
            if done > target:                       # first token still to decode
                target = min(target + 1, last)      # a one-token first chunk: TTFT
                self._ctl[0] = target
                rt.spec_ctl[1:2].copy_(self._ctl, non_blocking=True)
                sk.graph_launch(exe, stream.cuda_stream)
            while True:
                # Read the finished chunk, then launch the next. Not pipelined
                # on purpose: a chunk queued ahead would keep running after
                # the turn ends and delay the next request's prefill by a
                # whole chunk, to save a ~0.1 ms sync per chunk.
                n = target + 1 - done
                self._tok[:n].copy_(rt.hist[done:target + 1], non_blocking=True)
                self._ev.record(stream)
                self._ev.synchronize()
                yield self._tok[:n].tolist()
                done = target + 1
                if target >= last or cancel.is_set():
                    return
                target = min(target + self.chunk, last)
                self._ctl[0] = target
                rt.spec_ctl[1:2].copy_(self._ctl, non_blocking=True)
                sk.graph_launch(exe, stream.cuda_stream)

    def capture_buckets(self) -> None:
        """Capture every request-loop bucket (1k .. max_seq keys) up front so
        no request pays a ~50-100 ms first-use capture. Greedy graphs; a
        request with other sampling arguments recaptures what it uses."""
        import torch

        if not self.streaming:
            return
        rt = self.rt
        bucket = 1024
        with torch.no_grad():
            while True:
                b = min(bucket, rt.max_seq)
                if b not in rt._request_graphs:
                    rt._capture_spec_loop(b)
                if b >= rt.max_seq:
                    break
                bucket *= 2

    def warmup(self, prompt_len: int, new_tokens: int) -> None:
        import torch

        ids = torch.full((prompt_len,), 100, dtype=torch.int64)
        for _ in self.generate(ids, SamplingParams(max_tokens=new_tokens),
                               threading.Event()):
            pass
        torch.cuda.synchronize()
```

## 10. 服务端行为规则（必须一致）

以下由 `llm_serve` 实现，新模型自动获得；**不得**在胶水或 bundle 中改变这些行为。

| 规则 | 原因 / 依据 |
| --- | --- |
| engine 模式；`--host/--port` 由 host 提供 | flashcli 发布标准；与其它 bundle 一致 |
| 同时提供 OpenAI（chat / responses / completions）与 Anthropic（messages / count_tokens） | Claude Code 走 Anthropic；opencode、Agents SDK、Codex 类走 OpenAI |
| 请求中的 `model` 可为任意值 | 智能体常写死模型名 |
| batch=1 FIFO 排队，超过 `max_queue` 才 503 | 智能体常并发发请求（标题 + 主请求） |
| 推理内容单独返回：`reasoning_content` / `thinking` 块 / `reasoning` 项 | 各客户端的标准字段；`<think>` 标签不得漏进正文 |
| 推理预算：默认 8192；`reasoning_effort=low` 为 2048；不超过 `max_tokens − max(256, max_tokens/4)` | 开放式 agent 轮次会在推理里绕圈 16k~32k token（67~84 s）挡住单卡；小模型会在未关闭的 `<think>` 里写完整个答案。超预算由服务端收尾 `</think>` 并继续作答 |
| 带工具且未指定 temperature 的请求贪心解码（`tool_temperature=0`） | 4-bit 模型采样时会偶尔抄错上下文里的文件路径（60 个回放轮：采样 3 次、贪心 0 次） |
| 其它请求用 checkpoint 推荐采样 | 纯贪心更容易在推理里绕圈 |
| 工具调用宽容解析（缺 `<arg_key>`、工具名后直接写值、未知工具名仍作为调用返回） | 小模型常见；把标签当正文返回会让 agent 卡住 |
| 文本模型收到图片默认替换为提示文字（`image_input=reject` 改为 400） | 截图类工具结果不应让 agent 中断 |
| 错误按各协议格式返回；超长 prompt 为 400 `context_length_exceeded` | 客户端据此提示或压缩上下文 |
| 客户端断开即取消生成（一块之内释放 GPU） | 不让被放弃的请求占卡 |
| 默认日志每请求一行；调试存档由 `LLM_SERVE_DEBUG_DIR` / `LLM_SERVE_DEBUG_ALL` 开启 | 存档含对话内容，默认关闭 |

## 11. 接口清单与调用示例

| 方法 | 路径 | 规范 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/v1/chat/completions` | OpenAI | 流式（`stream_options.include_usage`）、`tools`/`tool_choice`/`parallel_tool_calls`（及旧 `functions`）、图片 part、`response_format`、`reasoning_effort`、`stop`、`seed`、`n` |
| `POST` | `/v1/responses` | OpenAI | `input`（文本 / message / `function_call` / `function_call_output` / reasoning）、`instructions`、function tools、`previous_response_id`、流式事件 |
| `POST` | `/v1/completions` | OpenAI | 旧版文本补全 |
| `POST` | `/v1/messages` | Anthropic | `system`（含 messages 内 system 轮）、text/image/`tool_use`/`tool_result`/`thinking` 块、`tools`/`tool_choice`、`thinking`（enabled/adaptive/disabled、`display: omitted`）、`stop_sequences`、流式事件 |
| `POST` | `/v1/messages/count_tokens` | Anthropic | 按真实 chat template 计数 |
| `GET` | `/v1/models`、`/v1/models/{id}` | 两者 | 带 `anthropic-version` 头返回 Anthropic 格式 |
| `GET` | `/health` | — | 忙闲、排队数、GPU、加载参数 |

推理通道开关：OpenAI `"reasoning_effort": "none"` 或 `"chat_template_kwargs": {"enable_thinking": false}`；
Anthropic `"thinking": {"type": "disabled"}`；Responses `"reasoning": {"effort": ...}`。

```bash
# OpenAI（流式 + 工具）
curl -N http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer <key>" -H 'Content-Type: application/json' -d '{
  "model": "<model-id>", "stream": true,
  "messages": [{"role": "user", "content": "北京现在天气怎么样？"}],
  "tools": [{"type": "function", "function": {"name": "get_weather", "description": "查询城市天气",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]}'

# Anthropic
curl -s http://127.0.0.1:8080/v1/messages \
  -H "x-api-key: <key>" -H 'anthropic-version: 2023-06-01' -H 'Content-Type: application/json' -d '{
  "model": "<model-id>", "max_tokens": 1024,
  "messages": [{"role": "user", "content": "用一句话介绍杭州。"}]}'
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="<key>")
r = client.chat.completions.create(model="<model-id>", messages=[{"role": "user", "content": "你好"}])
print(r.choices[0].message.reasoning_content, r.choices[0].message.content)

import anthropic
client = anthropic.Anthropic(base_url="http://127.0.0.1:8080", api_key="<key>")
with client.messages.stream(model="<model-id>", max_tokens=1024,
                            messages=[{"role": "user", "content": "写一首五言绝句"}]) as s:
    for text in s.text_stream:
        print(text, end="", flush=True)
```

智能体配置：

| 类型 | Base URL | Key | 模型名 |
| --- | --- | --- | --- |
| OpenAI 兼容（OpenAI SDK / Agents SDK、opencode、LangChain、Dify、Cline、Continue 等） | `http://<host>:<port>/v1` | `--api-key` 的值 | `<model-id>` |
| Anthropic 兼容（Claude Code、Anthropic SDK） | `http://<host>:<port>`（不带 `/v1`） | `--api-key` 的值 | `<model-id>` |

```bash
ANTHROPIC_BASE_URL=http://<host>:8080 ANTHROPIC_API_KEY=<key> claude --model <model-id>
```

## 12. 测试与验收

发布前必须全部完成（脚本在参考实现仓库 `scripts/serve/`）：

| 步骤 | 内容 | 验收 |
| --- | --- | --- |
| 1. 协议层离线测试 | 假模型驱动官方 SDK；推理/工具/stop 解析在任意切分点 | 全部 PASS（改过 `llm_serve` 必跑） |
| 2. 流式一致性 | 分块流式与整段生成逐 token 对比（贪心，多种块大小） | 全部一致 |
| 3. 官方 SDK 实测 | OpenAI / Anthropic：非流式、流式、工具与回填、强制工具、JSON、stop、长度、图片、Responses（含 `previous_response_id`）、count_tokens、长 prompt、并发 | 全部 PASS |
| 4. OpenAI Agents SDK | Responses 与 Chat Completions 两种模型，含并行工具与流式 | 4/4 |
| 5. 鲁棒性 | 断连释放 GPU、采样切换后可复现、长上下文、超长报错、max_tokens 截断 | 全部 PASS |
| 6. opencode 场景（22 个日常场景） | 问答、读/搜文件、命令、修 bug、写并运行、多文件项目、重命名、多轮、todo、plan、附件 | 服务端无 HTTP 错误（除超出上下文的正确 400）、无工具标签泄漏、无失控生成 |
| 7. Claude Code 多步工具任务 | 执行命令并写文件 | 完成（作为模型能力参考） |
| 8. `flashcli run` | 默认参数与模型专有测速参数 | 正常 |

注意：

- 跑 opencode 必须同时设置 `--dir`、环境变量 `PWD` 与 `OPENCODE_CONFIG`，并关闭 stdin
  （`opencode run` 会读管道 stdin），否则它可能根本没有请求被测服务（使用了默认云模型）；
  以服务端日志中确有请求为准。
- 测试必须用 `dist/` 发布树经 `flashcli serve` 运行，而不是开发目录。
- 排查用调试日志：`LLM_SERVE_DEBUG_DIR=<dir> LLM_SERVE_DEBUG_ALL=1 flashcli serve ...`，
  `gen-*.json` 含实际 prompt、原始输出 token 与解析事件，可区分"模型输出"与"协议/解析"问题。
- 精度参考：用简单一问一答对比首个答案 token 与 HF bf16 原模型（transformers 版本需与
  checkpoint 自带代码匹配；先确认两边 token id 完全一致）。

## 13. 打包、发布与版本

1. `pack` 只复制发布所需文件到 `dist/`（含 `llm_serve/`，不含本规范与测试脚本），去掉 `__pycache__`。
2. `flashcli bundle validate dist`；用 `flashcli serve dist --checkpoint ...` 完成第 12 节。
3. FlashHub：`POST /my/repositories/<id>/versions` 新建版本（版本号由平台自增，请求里的
   版本号会被忽略）；用分片上传保留目录结构（`upload/init` 带 `file_path`，0 字节文件也要
   上传一个空分片）；上传后用 `/repos/<org>/<name>:<ver>` 的文件列表逐个核对 md5。
4. 每个版本是独立文件集合：原生库未变时新版本仍要包含同样的 `.so`；不得覆盖旧版本。
5. 更新仓库介绍（readme / readme_en）中的 serve 用法、接口说明、版本号；从 FlashHub
   引用实际执行 `flashcli serve <org>/<name>:<ver>` 验证一次。

## 14. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `flashcli serve --ip ...` 报参数错误 | engine 模式用 `--host`；`ip`/`port` 不能声明在 serve_options |
| 客户端 422、路由不生效 | FastAPI 的 `Request` 等类型必须模块级 import（`from __future__ import annotations` 下局部 import 会被当成 query 参数） |
| 正文里出现 `<tool_call>…` 原文 | 模型输出格式错误或 `tool_parser` 选错；看 `gen-*.json` 的原始输出 |
| 一轮推理不结束、所有请求变慢 | 推理预算被关闭或胶水未实现 `encode` |
| 只有推理、没有回答 | `max_tokens` 太小或预算规则被改；协议层会把预算限制在给回答留空间的范围内 |
| 智能体偶尔"文件不存在"，路径里有错字 | 低比特量化的复制噪声；确认带工具请求为贪心（`tool_temperature=0`） |
| 首个请求慢几十 ms | 新 bucket / 新 prompt 长度的图捕获；加载时预捕获或 `--warmup` |
| 长 prompt 被拒 | `--max-seq` 与 `--prefill-cap` 一起调大（只能启动时设置）；客户端上下文上限与之一致 |
| 显存不足时精度下降 | 运行时按剩余显存选择 KV 存储（见 `/health` 的 `kv8_only`），独占 GPU 运行 |

---

## 附录 A. `llm_serve` 模块说明与获取方式

| 模块 | 内容 |
| --- | --- |
| `adapter.py` | 胶水契约 `ModelAdapter`、`Prompt`、`SamplingParams`（第 5 节全文） |
| `datatypes.py` | 协议无关的请求 / 事件类型（附录 B 全文） |
| `engine.py` | `LLMEngine`：单 GPU FIFO 队列、取消、推理预算、采样默认值、文本流水线 |
| `parsers.py` | stop 字符串、`<think>` 拆分、工具调用格式（glm45 / hermes / qwen3_coder）与宽容解析 |
| `openai_api.py` | Chat Completions / Completions / Responses 的解析与 SSE |
| `anthropic_api.py` | Messages / count_tokens 的解析与 SSE |
| `media.py` | 图片输入（data URL、base64、http(s) URL）解析 |
| `server.py` | 路由、鉴权、`/v1/models`、`/health`、`LLMServeEngine`（附录 C） |
| `debug.py` | 调试日志与请求/生成存档（环境变量开启） |

获取：从参考 bundle 原样复制整个 `llm_serve/` 目录（不得修改）：

```bash
flashcli bundle sync xym/spark_x26_4b:1.0.7      # 拉取 bundle 文件（不含权重）
cp -r ~/.flashcli/bundles/spark_x26_4b/1.0.7/llm_serve <your-bundle>/
```

## 附录 B. 数据类型（完整代码）

`llm_serve/datatypes.py`：

```python
"""Protocol-neutral request / event types shared by the OpenAI and Anthropic
front doors and the model glue.

Both HTTP dialects are parsed into a ``ChatRequest`` (messages with typed
parts, tools, sampling, reasoning switches); the engine answers with a stream
of ``Event`` objects (reasoning text, answer text, complete tool calls and one
final ``done``). Nothing here imports torch, so the same types serve every
model bundle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextPart:
    text: str
    type: str = "text"


@dataclass
class ImagePart:
    """An input image: raw bytes (decoded data URL / base64) or a remote URL."""

    data: bytes | None = None
    media_type: str | None = None
    url: str | None = None
    detail: str | None = None
    type: str = "image"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    #: the model's raw argument text when it did not parse as an object
    raw_arguments: str | None = None

    def arguments_json(self) -> str:
        if self.raw_arguments is not None and not self.arguments:
            return self.raw_arguments
        return json.dumps(self.arguments, ensure_ascii=False)


@dataclass
class Message:
    role: str                      # system | user | assistant | tool
    parts: list[Any] = field(default_factory=list)   # TextPart | ImagePart
    reasoning: str | None = None   # assistant thinking carried in history
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def text(self) -> str:
        return "".join(p.text for p in self.parts if isinstance(p, TextPart))

    def images(self) -> list[ImagePart]:
        return [p for p in self.parts if isinstance(p, ImagePart)]


@dataclass
class Tool:
    name: str
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}})

    def as_openai(self) -> dict[str, Any]:
        """The ``{"type": "function", "function": {...}}`` form chat templates
        expect."""
        fn: dict[str, Any] = {"name": self.name}
        if self.description:
            fn["description"] = self.description
        fn["parameters"] = self.parameters or {"type": "object", "properties": {}}
        return {"type": "function", "function": fn}


@dataclass
class ChatRequest:
    messages: list[Message]
    tools: list[Tool] = field(default_factory=list)
    #: "auto" | "none" | "required" | a tool name (forced)
    tool_choice: str = "auto"
    parallel_tool_calls: bool = True
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    seed: int | None = None
    stop: list[str] = field(default_factory=list)
    #: None = the server default
    enable_thinking: bool | None = None
    #: "low" | "medium" | "high" | None
    reasoning_effort: str | None = None
    #: reasoning tokens before the server closes the thinking channel
    #: (Anthropic ``budget_tokens``); None = the server's default
    thinking_budget: int | None = None
    #: None | {"type": "json_object"} | {"type": "json_schema", "schema": ..., "name": ...}
    response_format: dict[str, Any] | None = None
    #: free-form per-dialect extras the glue may read (chat_template_kwargs, ...)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    ttft_s: float | None = None
    wall_s: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def decode_tok_per_s(self) -> float:
        if self.ttft_s is None or self.completion_tokens <= 1:
            return 0.0
        dt = self.wall_s - self.ttft_s
        return (self.completion_tokens - 1) / dt if dt > 0 else 0.0


@dataclass
class Event:
    """One step of a generation as both front doors see it.

    ``kind`` is ``reasoning`` / ``text`` (``text`` holds the delta),
    ``tool_call`` (``tool_call`` is complete), or ``done`` (``finish_reason``
    in {stop, length, tool_calls}, ``stop_sequence`` when a stop string hit,
    ``usage``).
    """

    kind: str
    text: str = ""
    tool_call: ToolCall | None = None
    finish_reason: str | None = None
    stop_sequence: str | None = None
    usage: Usage | None = None


class APIError(Exception):
    """An error with an HTTP status; each dialect renders its own body."""

    def __init__(self, status: int, message: str, *,
                 kind: str = "invalid_request_error",
                 param: str | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.kind = kind
        self.param = param
        self.code = code
```

## 附录 C. `LLMServeEngine`（flashcli 入口基类，完整代码）

摘自 `llm_serve/server.py`：

```python
class LLMServeEngine:
    """flashcli ``ServeEngine`` over a ``ModelAdapter``.

    Subclass and set ``adapter_factory``. Serve options understood here (the
    rest go to ``ModelAdapter.load``): ``model_name``, ``api_key``,
    ``default_max_tokens``, ``max_queue``, ``image_input``
    (placeholder|reject), ``enable_thinking``, ``max_thinking_tokens``,
    ``tool_temperature``.
    """

    adapter_factory: Callable[[], ModelAdapter]

    def __init__(self) -> None:
        self.adapter: ModelAdapter | None = None
        self.engine: LLMEngine | None = None
        self._api_key: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def model_id(self) -> str:
        return self.adapter.model_id if self.adapter is not None else ""

    def load(self, checkpoint: Any, preset: Any = None, **options: Any) -> None:
        del preset
        if self.engine is not None:
            return
        adapter = type(self).adapter_factory()
        adapter.load(str(checkpoint), **options)
        self.adapter = adapter
        self._api_key = str(options.get("api_key") or "") or None
        self.engine = LLMEngine(
            adapter,
            default_max_tokens=int(options.get("default_max_tokens") or 4096),
            max_queue=int(options.get("max_queue") or 32),
            image_policy=str(options.get("image_input") or "placeholder"),
            enable_thinking=_bool(options.get("enable_thinking"),
                                  adapter.default_enable_thinking),
            max_thinking_tokens=int(8192 if options.get("max_thinking_tokens") is None
                                    else options["max_thinking_tokens"]),
            tool_temperature=float(0.0 if options.get("tool_temperature") is None
                                   else options["tool_temperature"]))
        log.info("serving %s (context %d tokens, auth %s)", adapter.model_id,
                 adapter.context_length, "on" if self._api_key else "off")

    def warmup(self, spec: str | None) -> None:
        if self.adapter is not None and spec:
            self.adapter.warmup(spec)

    def register_routes(self, app: Any) -> None:
        if self.engine is None:
            raise RuntimeError("ServeEngine.load() has not been called")
        register_routes(app, self.engine, api_key=self._api_key)

    # The flashcli protocol's chat()/chat_stream() back the host's own
    # /v1/chat/completions, which register_routes shadows; they are kept for
    # completeness and run the same OpenAI path.
    def _openai_body(self, request: Any) -> dict[str, Any]:
        msgs = []
        for m in getattr(request, "messages", []) or []:
            msgs.append({"role": getattr(m, "role", "user"),
                         "content": getattr(m, "content", None),
                         **({"tool_calls": m.tool_calls} if getattr(m, "tool_calls", None)
                            else {})})
        body = {"messages": msgs, "max_tokens": getattr(request, "max_tokens", None),
                "temperature": getattr(request, "temperature", None),
                "top_p": getattr(request, "top_p", None),
                "seed": getattr(request, "seed", None),
                "stop": getattr(request, "stop", None),
                "tools": getattr(request, "tools", None)}
        body.update(getattr(request, "extras", None) or {})
        return body

    def _run(self, coro: Any) -> Any:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            threading.Thread(target=self._loop.run_forever, daemon=True,
                             name="llm-serve-sync").start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def chat(self, request: Any) -> Any:
        from flashcli_bundle.protocol import ChatResult

        assert self.engine is not None
        req, _ = oai.parse_chat_request(self._openai_body(request))

        async def go():
            return await self.engine.complete(await self.engine.prepare(req))

        c = self._run(go())
        return ChatResult(
            content=c.text or None,
            tool_calls=[oai._tool_call_json(t) for t in c.tool_calls],
            finish_reason=c.finish_reason if c.finish_reason in
            ("stop", "length", "tool_calls") else "stop",
            usage=oai._usage_json(c.usage), reasoning_content=c.reasoning or None)

    def chat_stream(self, request: Any) -> Iterator[Any]:
        from flashcli_bundle.protocol import ChatChunk

        result = self.chat(request)
        if result.reasoning_content:
            yield ChatChunk(reasoning_delta=result.reasoning_content)
        if result.content:
            yield ChatChunk(content_delta=result.content)
        if result.tool_calls:
            yield ChatChunk(tool_calls=result.tool_calls)
        yield ChatChunk(finish_reason=result.finish_reason, usage=result.usage)
```
