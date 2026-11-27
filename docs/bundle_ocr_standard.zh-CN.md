# OCR 类模型 Bundle 打包规范（OpenAI 兼容服务 + 多图/批量）

<p align="right"><a href="bundle_ocr_standard.md">English</a> · <strong>简体中文</strong></p>

> **类别补充。** 通用 manifest、目录结构、权重、运行时与发布规则仍以 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)（英文：[bundle_publish_standard.md](bundle_publish_standard.md)）为准；本页只补充 OCR 专有要求。
>
> **网关透传。** OCR bundle 使用 `format_version: 4`、engine 模式、`ServeEngine`，并通过 `register_routes(app)` 提供原生 `/v1/ocr`、`/v1/ocr/batch`、`/v1/ocr/info` 路由。flashserver `/v1` 网关会把这些自定义路径透传到模型 serve 端点，因此同一个 base URL 同时暴露标准 OpenAI 路由和原生 OCR 路由。
>
> **通用规则不重复。** manifest/目录/entry/运行时/权重/发布规则见 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)；engine 模式的 host 行为（标准路由、鉴权、并发、请求日志、SSE 传输、错误转换）见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)。本文只补充 OCR 专有路由、schema、限制和验收。

> 适用：FlashRT 适配的 OCR（文本检测 + 文本识别）模型，以 flashcli bundle
> （`format_version: 4`）发布到 FlashHub，并通过 `flashcli serve` 提供
> HTTP 服务。
>
> 本文是 [flashcli Model Bundle 发布标准](bundle_publish_standard.zh-CN.md)
> 在 **OCR 服务**方面的补充规则：通用目录、manifest、`.so` 命名、权重与
> 溯源要求仍以发布标准为准；本文只规定 OCR bundle 额外必须满足的内容。
> 它不是 LLM 规范；LLM 请使用
> [llm_bundle_standard.zh-CN.md](llm_bundle_standard.zh-CN.md)。

参考实现（已按本规范发布并实测）：

| 模型 | FlashHub 引用 | 说明 |
|---|---|---|
| PP-OCRv6 medium det + rec | `aodianyun/paddleocr_v6:1.0.3` | 参考实现；RTX 3060 / 4060 Ti / 5060 Ti（SM86 / SM89 / SM120） |

参考实现的完整项目级契约见 FlashRT 仓库
`docs/paddleocr_v6_serve.zh-CN.md`；本文抽取其中的 **通用要求**，供其他 OCR
模型复用。

---

## 目录

1. 目标与总体要求
2. 架构：协议层 `ocr_serve` 与模型胶水
3. 发布目录结构
4. manifest（`flashcli-bundle.json`）规则
5. 胶水接口：`ServeEngine` + 后端契约
6. 入口：`serve.py` / `run.py`
7. OCR 数据模型：`ocr` 扩展对象
8. OpenAI Chat Completions 扩展
9. OpenAI Responses 扩展
10. 原生 `/v1/ocr`
11. 批量多输出 `/v1/ocr/batch`
12. 图片输入（URL / base64 / 本地路径）
13. 服务端行为规则（必须一致）
14. 接口清单与调用示例
15. 测试与验收
16. 打包、发布与版本
17. 常见问题
附录 A. `ocr` 对象 schema
附录 B. 错误码

---

## 1. 目标与总体要求

一个 OCR bundle 的 `flashcli serve` **必须**：

1. 使用 **engine 模式** 的 `ServeEngine`，监听地址/端口由 host 的
   `--host`（默认 `0.0.0.0`）/ `--port`（默认 `8000`）提供；
2. 同时提供 **OpenAI 兼容**（`/v1/chat/completions`、`/v1/responses`）与
   **原生 OCR**（`/v1/ocr`）接口；标准模型/健康路由由 host 持有；
3. 支持 **多图输入**：一次请求可带多张图片，按输入顺序返回逐图结果；
4. 支持 **批量 JSON 多输出** `/v1/ocr/batch`：一次调用指定多个输入
   （每项可多图）与每项输出格式，按顺序返回 `results[]`；
5. 支持 **本地路径 / `file://` / data URL / 裸 base64 / http(s) URL**
   五类图片输入（本地路径可配置沙箱或关闭）；
6. 在标准响应之外提供顶层 `ocr` 扩展对象（逐图、逐行文本/置信度/多边形）；
7. 支持 SSE 流式（Chat Completions 与 Responses）；
8. 启动 **不执行校准**：不加载校准数据集、不执行校准前向；bundle 内
   不含校准数据；
9. 复用统一的协议层 `ocr_serve/`（不按模型修改），模型差异只写在
   “胶水/后端”里；
10. 通过第 15 节验收后再发布。

用户侧的使用方式对所有 OCR bundle 一致：

```bash
flashcli serve <org>/<name>:<version> --host 0.0.0.0 --port 8080 --api-key <key>
# OpenAI 兼容：  base_url = http://<host>:8080/v1
# 原生 OCR：     POST http://<host>:8080/v1/ocr
# 批量：         POST http://<host>:8080/v1/ocr/batch
```

---

## 2. 架构：协议层 `ocr_serve` 与模型胶水

```text
                 flashcli serve <ref> --host H --port P [--api-key K ...]
                                   │  engine 模式：host 建 FastAPI app、监听端口
                                   ▼
 ┌──────────── ocr_serve/（协议层文件：所有 OCR bundle 共用，原样复制，禁止按模型修改）────────────┐
 │ server.py      /v1/ocr  /v1/ocr/batch  /v1/ocr/info  OCR FIFO 队列、SSE                     │
 │                （host 持有标准路由、鉴权和并发门）                                           │
 │ openai_api.py  OpenAI 两种方言的解析、OCR 结果塑形、SSE 事件                                 │
 │ media.py       data URL / base64 / http(s) / 本地路径解析、大小与 SSRF 校验                  │
 │ datatypes.py   与框架无关的请求/结果/错误类型                                                 │
 └───────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                             │  后端契约（第 5 节）
 ┌───────────────────────────────────────────▼───────────── 每个模型自己写 ─────────────────────┐
 │ ocr_serve/backend.py  load / warmup / run_image / info；图捕获边界管理（模型胶水）           │
 │ serve.py              class ServeEngine(ocr_serve.server.OcrServeEngine): pass              │
 │ run.py                flashcli run 入口（复用同一后端）                                      │
 └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

规则：

- `ocr_serve/` 的协议文件（`server.py` / `openai_api.py` / `media.py` /
  `datatypes.py` / `__init__.py`）只依赖 `fastapi` / `uvicorn` /
  `pydantic` 与标准库，不依赖 torch；它们负责 OCR 专有的请求解析、结果塑形、
  SSE、批量处理、图片校验和 OCR FIFO 队列。标准路由、鉴权、并发门、请求日志
  和错误信封由 host 持有。
- `ocr_serve/backend.py` 是模型胶水，可以依赖 torch/OpenCV 等运行时库；
  移植到其他 OCR 模型时替换它的实现，保持接口不变。
- 胶水不处理 HTTP/JSON/SSE/排队；协议层不认识任何具体 OCR 模型。
- 需要修改协议层时，同步到所有 OCR bundle，保持行为一致。

---

## 3. 发布目录结构

```text
<bundle>/                         # 发布根（dist/）
├── flashcli-bundle.json          # manifest（第 4 节）
├── serve.py                      # flashcli serve 入口（ServeEngine，engine 模式）
├── run.py                        # flashcli run 入口（RunEngine，engine 模式）
├── ocr_serve/
│   ├── __init__.py  datatypes.py  media.py       # 协议层，原样复制
│   ├── openai_api.py  server.py                  # 协议层，原样复制
│   └── backend.py                                # 模型胶水，按模型替换
├── flash_rt/                     # entry 可达的 FlashRT Python 源码（无 .so）
├── runtime/<env-key>/*.so        # 每个 environment 的原生库
└── README.md                     # 使用说明与接口摘要
```

- 发布树必须最小：本规范文档、测试脚本、`.gitignore`、缓存、校准/测试
  图片、权重不进 `dist/`。
- 不要把模块命名为 `types.py` 等与标准库重名的名字（会遮蔽 stdlib）。

---

## 4. OCR 专有 manifest 设置

通用 manifest schema、entry、依赖和权重见 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)。这里只列 OCR 专有的 serve_options 和资源要求。

### 4.3 统一的 serve_options（所有 OCR bundle 必须提供，名字与语义一致）

```json
[
  {"name": "model_name", "type": "string", "default": "<ocr-model>", "phase": "load",
   "help": "Model id reported in responses (requests may name any model)."},
  {"name": "api_key", "type": "string", "default": "", "phase": "load",
   "help": "Require this key on /v1/* as 'Authorization: Bearer <key>' or 'x-api-key: <key>'."},
  {"name": "device", "type": "string", "default": "cuda", "phase": "load",
   "help": "CUDA device string."},
  {"name": "max_queue", "type": "integer", "default": 32, "phase": "load",
   "help": "Requests allowed to wait for the single GPU slot (FIFO); beyond it 503 (0 = unlimited)."},
  {"name": "max_wait_sec", "type": "float", "default": 60.0, "phase": "load",
   "help": "Longest time a request may wait for the GPU slot before 503 (0 = forever)."},
  {"name": "max_images", "type": "integer", "default": 8, "phase": "load",
   "help": "Maximum images per request (or per batch item)."},
  {"name": "max_batch", "type": "integer", "default": 32, "phase": "load",
   "help": "Maximum items in one /v1/ocr/batch call."},
  {"name": "max_image_bytes", "type": "integer", "default": 20971520, "phase": "load",
   "help": "Maximum decoded image size in bytes (default 20 MiB)."},
  {"name": "image_url_timeout_sec", "type": "float", "default": 15.0, "phase": "load",
   "help": "Timeout for downloading an http(s) image URL."},
  {"name": "image_url_ports", "type": "string", "default": "80,443", "phase": "load",
   "help": "Comma-separated ports allowed in http(s) image URLs (empty: any port)."},
  {"name": "allow_private_image_urls", "type": "boolean", "default": false, "phase": "load",
   "help": "Allow image URLs resolving to loopback/private/link-local addresses (SSRF guard)."},
  {"name": "allow_local_image_paths", "type": "boolean", "default": true, "phase": "load",
   "help": "Accept local image paths and file:// URLs and read the file directly."},
  {"name": "local_image_root", "type": "string", "default": "", "phase": "load",
   "help": "If set, local paths must resolve inside this directory (empty: any readable path)."},
  {"name": "warmup", "type": "string", "default": "", "phase": "warmup",
   "help": "Comma-separated image paths to pre-capture graphs before serving."}
]
```

- 模型专有参数（阈值、输入尺寸上限、图捕获上限等）接在后面，由
  `load(**options)` 读取。
- `warmup` 是 phase=`warmup`；host 会在加载后调用 `ServeEngine.warmup(spec)`。
- `run_options` 按发布标准声明（`image`、`output`、`json_output`、`device` 等）。

## 5. 胶水接口：`ServeEngine` + 后端契约

### 5.1 `ServeEngine`

`serve.py` 继承协议层基类；`OcrServeEngine.__init__` 创建
`ocr_serve.backend.OcrBackend`，因此移植其他模型时只需替换
`ocr_serve/backend.py` 的实现，`serve.py` 保持三行：

```python
"""flashcli serve entry (engine mode) for <model>."""
from __future__ import annotations

from ocr_serve.server import OcrServeEngine


class ServeEngine(OcrServeEngine):
    """<model> det+rec behind the flashcli serve HTTP surface."""
```

`OcrServeEngine` 已实现：

- `model_id` / `load` / `warmup` / `chat` / `chat_stream`（flashcli
  `ServeEngine` 协议）；
- `register_routes(app)`：鉴权、日志、FIFO 队列、全部 HTTP 路由；
- 请求解析、结果塑形、SSE、批量与错误处理。

### 5.2 后端契约

每个模型实现一个后端类（`backend.py`）：

```python
class Backend:
    device: str = "cuda"
    precision: str = "fp16"

    def load(self, checkpoint: str | Path, options: dict) -> None: ...
    def warmup(self, spec: str | None) -> None: ...
    def run_image(self, data: bytes) -> ImageResult: ...
    def info(self) -> dict: ...
```

- `load`：只加载一次、常驻显存；读取 manifest 传入的 checkpoint。
- `warmup`：按逗号分隔的图片路径预捕获/预热；空值不做事。
- `run_image`：解码一张图片并执行完整 OCR，返回
  `ImageResult(width, height, rec_texts, rec_scores, rec_polys, det_scores, e2e_ms, image_bytes)`。
- `info`：`/v1/ocr/info` 的运行状态（device、GPU、捕获状态等）。
- 后端必须自行串行化 GPU 调用（协议层已保证单槽位，但 `chat()` 同步
  路径也可能被 host 调用）。
- **不得**在 `load`/`warmup` 中加载校准数据或执行校准前向。

参考实现：`paddleocr_v6` 的 `ocr_serve/backend.py`。

---

## 6. 入口

host 按 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md) 加载 `ServeEngine` / `RunEngine`；OCR bundle 不得自己启动 HTTP 服务。`ocr_serve` 协议层通过 `ServeEngine.register_routes` 挂载。

## 7. OCR 数据模型：`ocr` 扩展对象

所有 OpenAI 响应在标准字段之外增加顶层 `ocr`：

```json
{
  "object": "ocr.result",
  "version": 1,
  "engine": "<engine-id>",
  "model": "<model-id>",
  "device": "cuda",
  "precision": "fp16",
  "image_count": 1,
  "line_count": 2,
  "text": "第一行\n第二行",
  "e2e_ms": 15.23,
  "images": [
    {
      "index": 0,
      "width": 896,
      "height": 528,
      "text": "第一行\n第二行",
      "line_count": 2,
      "lines": [
        {"text": "第一行", "score": 0.9987, "polygon": [[12, 30], [220, 30], [220, 62], [12, 62]]},
        {"text": "第二行", "score": 0.9971, "polygon": [[12, 70], [300, 70], [300, 102], [12, 102]]}
      ],
      "det_scores": [0.987, 0.981],
      "e2e_ms": 15.23,
      "image_bytes": 123456
    }
  ]
}
```

字段与语义、请求级选项（`format` / `line_separator` /
`include_polygons` / `include_scores` / `include_det_scores`）见附录 A。
`format=json` 时 assistant content 是该对象的 JSON 字符串；`format=text`
时 content 为逐行文本。

---

## 8. OpenAI Chat Completions 扩展

`POST /v1/chat/completions`

- 图片 content part：`image_url` 与 `input_image`；`image_url` 可以是
  `{"url": "..."}` 或直接字符串。
- 一条消息可含多张图片；多条消息的图片按出现顺序合并。
- 至少一张图片；否则 400 `image_required`。
- 支持 `stream: true`；文本格式按行增量，JSON 格式一次发送。
- 最终流式 chunk 带 `finish_reason: "stop"`、`usage` 与完整 `ocr`。
- `response_format: {"type": "json_object"}` 等价于 `ocr.format=json`。
- `max_tokens` / `temperature` / `top_p` / `stop` 等不生效（OCR 不生成
  token）；`n>1`、`tools` / `functions`、未知 part 类型返回 400。

响应示例见第 14 节。

---

## 9. OpenAI Responses 扩展

`POST /v1/responses`

- `input` 为字符串或 item 列表；item 支持 `message` / `input_text` /
  `input_image`；内容 part 接受 `text` / `image_url` 别名。
- 至少一个 `input_image`；否则 400。
- 不支持 `previous_response_id`、`tools`、`function_call` /
  `function_call_output` / `reasoning` item。
- 非流式返回 `object: "response"`、`output[]`、`output_text`、`usage`、
  `ocr`。
- 流式事件：`response.created`、`response.in_progress`、
  `response.output_item.added`、`response.content_part.added`、
  `response.output_text.delta`、`response.output_text.done`、
  `response.content_part.done`、`response.output_item.done`、
  `response.completed`（含 `usage` 与 `ocr`）。

`usage` 必须包含 `input_tokens_details.cached_tokens` /
`cache_write_tokens` 与 `output_tokens_details.reasoning_tokens`，否则
官方 OpenAI SDK 解析失败。

---

## 10. 原生 `/v1/ocr`

`POST /v1/ocr`

```json
{
  "model": "<model-id>",
  "images": [
    "https://example.com/page.jpg",
    "/data/pages/page-1.png",
    "file:///data/pages/page-2.png",
    {"path": "/data/pages/page-3.png"},
    "data:image/png;base64,..."
  ],
  "line_separator": "\n",
  "include_polygons": true,
  "include_scores": true,
  "include_det_scores": true
}
```

- `image` 与 `images` 可同时出现；`images` 在前、`image` 在后。
- `images[]` 元素可以是字符串或对象（`url` / `path` / `file` /
  `file_url` / `data_url` / `base64` / `image_url` / `data`）。
- 响应为 `ocr.result`，额外带 `created`。
- 不提供流式。

---

## 11. 批量多输出 `/v1/ocr/batch`

一次 JSON 调用指定多个输入，每项有独立 `id`、图片与输出格式：

```json
{
  "continue_on_error": true,
  "requests": [
    {"id": "page-1", "image": "/data/pages/1.png", "format": "json"},
    {"id": "page-2", "images": ["https://example.com/2.jpg", "/data/pages/2b.png"],
     "format": "text", "include_polygons": false}
  ]
}
```

- `requests` 也可写作 `inputs` / `items`。
- 每项支持 `image` / `images`、`format`（text/json）、`ocr` 选项对象；
  顶层 `format` / `line_separator` / `include_*` 提供默认值。
- 响应 HTTP 200，`object: "ocr.batch"`，`results[]` 与输入顺序一一对应：

```json
{
  "object": "ocr.batch",
  "batch_size": 2,
  "succeeded": 2, "failed": 0, "skipped": 0,
  "e2e_ms": 40.1,
  "results": [
    {"index": 0, "id": "page-1", "status": "ok", "format": "json",
     "content": "{...}", "ocr": {"...": "..."}, "e2e_ms": 18.2},
    {"index": 1, "id": "page-2", "status": "ok", "format": "text",
     "content": "第一行\n第二行", "ocr": {"...": "..."}, "e2e_ms": 21.9}
  ]
}
```

- `continue_on_error=true`（默认）：单项失败不影响后续，失败项
  `status: "error"` + `error`；
- `continue_on_error=false`：首个失败后剩余项 `status: "skipped"`；
- 重复 `id` 判为该单项错误；
- 整个批量只占一次 GPU 槽位，项间串行。

---

## 12. 图片输入（URL / base64 / 本地路径）

支持：

1. Data URL：`data:image/png;base64,....`；
2. 裸 base64（标准或 URL-safe）；
3. `http://` / `https://` URL；
4. 本地路径：`/abs/path.png`、`./` / `../` / `~/` 开头、带图片扩展名的
   相对路径（`images/page.jpg`）；
5. `file://` URL（空 host 或 `localhost`）。

规则：

- `max_image_bytes` 对解码后字节数生效；
- URL：默认 80/443、拒绝私网/loopback、每跳重定向校验、最多 4 跳、
  超时 `image_url_timeout_sec`；
- 本地路径：`allow_local_image_paths`（默认 true）；
  `local_image_root` 非空时路径 `resolve()` 后必须位于该目录内；
  相对路径设置 root 时相对 root，否则相对进程 cwd；
- 本地文件不存在/不是普通文件 -> 400 `image_not_found`；非图片内容 ->
  400 `unsupported_image_type`；
- 本地路径默认允许进程可读任意文件；公网/多租户部署必须设置
  `local_image_root` 或关闭本地路径；
- 支持 JPEG / PNG / WebP / BMP / TIFF / GIF；解码失败返回 400。

---

## 13. 服务端行为规则（必须一致）

> engine 模式的 host 行为（标准路由、鉴权、并发门、请求日志和错误信封）见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)，本文不重复。下表只列 OCR 专有的媒体/队列行为。

| 规则 | 原因 / 依据 |
| --- | --- |
| OpenAI Chat Completions + Responses + 原生 OCR | 客户端直接复用 OpenAI SDK；原生接口给批处理 |
| 请求中的 `model` 可为任意值 | 客户端常写死模型名 |
| 单 GPU 单槽位，batch=1 FIFO；超过 `max_queue` 才 503 | OCR 前向独占 GPU |
| 启动不校准；bundle 无校准数据 | 避免启动耗时与数据泄漏 |
| 图片 URL 私网/loopback 默认拒绝；本地路径可沙箱 | SSRF / 任意文件读取防护 |
| 多图按输入顺序返回，content 按空行拼接 | 可预测的多图语义 |
| 批量单项错误隔离（默认） | 批处理不因一张坏图整体失败 |
| 流式文本按行增量，拼接与非流式逐字节一致 | 客户端可边收边用 |
| 批量项错误不改 HTTP 状态 | 客户端统一处理 |
| 客户端断开后停止发送；当前帧不中断 | OCR 单帧粒度，无法安全杀死 kernel |

---

## 14. 接口清单与调用示例

| 方法 | 路径 | 规范 | 说明 |
|---|---|---|---|
| POST | `/v1/chat/completions` | OpenAI | 图片 part、流式、`ocr` 扩展 |
| POST | `/v1/responses` | OpenAI | `input_image`、流式事件、`ocr` 扩展 |
| POST | `/v1/ocr` | 原生 | 单图/多图结构化结果 |
| POST | `/v1/ocr/batch` | 原生 | JSON 批量多输出 |
| GET | `/v1/ocr/info` | 原生 | 能力、限制、运行状态 |

```bash
# Chat Completions（本地路径）
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer <key>" -H 'Content-Type: application/json' \
  -d '{"model":"<model>","messages":[{"role":"user","content":[
        {"type":"image_url","image_url":"/data/pages/page.png"}]}],
      "ocr":{"format":"json"}}' | jq .

# 多图 + 批量多输出
curl -s http://127.0.0.1:8080/v1/ocr/batch \
  -H "Authorization: Bearer <key>" -H 'Content-Type: application/json' \
  -d '{"requests":[
        {"id":"a","image":"/data/pages/a.png","format":"json"},
        {"id":"b","images":["/data/pages/b1.png","/data/pages/b2.png"],"format":"text"}]}' | jq .
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="<key>")
r = client.chat.completions.create(
    model="<model>",
    messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": "/data/pages/page.png"}]}],
    extra_body={"ocr": {"format": "json"}},
)
print(r.model_extra["ocr"]["images"][0]["lines"])
```

---

## 15. 测试与验收

发布前必须全部完成：

| 步骤 | 内容 | 验收 |
| --- | --- | --- |
| 1 | `flashcli bundle validate <dist>` | `[ok]` |
| 2 | `flashcli run <dist>` | 文本/分数/多边形与优化回执一致 |
| 3 | `flashcli serve <dist>`（目标 GPU 矩阵） | 启动成功，`/v1/ocr/info` 可响应 |
| 4 | Chat Completions 非流式/流式 | content 逐字节一致；`ocr` 完整 |
| 5 | Responses 非流式/流式 | `response.completed` + `ocr`；官方 SDK 可解析 |
| 6 | `/v1/ocr` 单图/多图 | `image_count`、顺序、逐图文本正确 |
| 7 | `/v1/ocr/batch` | 顺序/id/格式正确；单项失败隔离；`skipped` 语义 |
| 8 | 本地路径 | 绝对/相对/`file://` 成功；root 外与关闭时 400 |
| 9 | 错误与限制 | 无图、超大图、私网 URL、tools、n>1、坏 JSON |
| 10 | 并发/排队 | 单槽位串行；超过队列 503 |
| 11 | 精度 | 与 `flashcli run` / 优化回执逐行一致 |
| 12 | 包内容 | 无权重、无校准数据、无测试图片/缓存；`.so` 为必需最小集 |
| 13 | 清理 | 运行缓存、日志、`__pycache__` 不进包 |

测试必须用 `dist/` 发布树经 `flashcli serve` 运行，而不是开发目录。
远端调试进程必须持有共享调试锁（如 `/debuglock/rsi.lock`），避免与其他
任务同时占用 GPU。

---

## 16. 打包与发布

发布树、manifest、`.so` 布局、权重、溯源和 FlashHub 上传按 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)。OCR 专有验收见 §15。

## 17. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `flashcli serve --ip ...` 报参数错误 | engine 模式用 `--host`；`ip`/`port` 不能声明在 serve_options |
| 客户端 422、路由不生效 | FastAPI 的 `Request` 等类型必须模块级 import（`from __future__ import annotations` 下局部 import 会被当成 query 参数） |
| OpenAI SDK 解析 Responses 失败 | `usage` 缺少 `input_tokens_details` / `output_tokens_details`，或缺少 `parallel_tool_calls` / `tool_choice` / `tools` |
| 流式 content 与非流式不一致 | `content_deltas` 必须按 `line_separator` 切分并原样拼回；JSON 格式不要按行切 |
| 多图顺序错 | 按消息/数组出现顺序收集图片，不要按角色或字典键排序 |
| 本地路径 403/400 | 检查 `allow_local_image_paths`、`local_image_root`、文件是否存在及 `resolve()` 后是否在 root 内 |
| 首个请求慢 | 新帧尺寸/新识别宽度会捕获图；用 `--warmup` 预捕获 |
| 显存随尺寸增长 | 捕获集按帧形状/识别宽度增长；设置 `max_rec_widths`，或按尺寸分组批处理 |
| 公网服务器可读任意文件 | 默认允许本地路径；必须设置 `local_image_root` 或关闭本地路径 |

---

## 附录 A. `ocr` 对象 schema

```json
{
  "object": "ocr.result",
  "version": 1,
  "engine": "string",
  "model": "string",
  "device": "cuda",
  "precision": "fp16",
  "image_count": 1,
  "line_count": 2,
  "text": "string",
  "e2e_ms": 15.23,
  "images": [{
    "index": 0,
    "width": 896,
    "height": 528,
    "text": "string",
    "line_count": 2,
    "lines": [{
      "text": "string",
      "score": 0.9987,
      "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]
    }],
    "det_scores": [0.987],
    "e2e_ms": 15.23,
    "image_bytes": 123456
  }]
}
```

请求级 OCR 选项：

| 选项 | 类型 / 默认 | 说明 |
| --- | --- | --- |
| `format` | `text` / `text` | `text`：content 为纯文本；`json`：content 为 `ocr` 对象的 JSON 字符串 |
| `line_separator` | string / `\n` | 行分隔符，非空，≤ 8 字符 |
| `include_polygons` | boolean / `true` | 是否在 `lines[]` 中包含 `polygon` |
| `include_scores` | boolean / `true` | 是否包含识别 `score` |
| `include_det_scores` | boolean / `true` | 是否包含 `det_scores` |

未知 `ocr` 键返回 400（避免拼写错误静默失效）。

## 附录 B. 错误码

| HTTP | `code` | 场景 |
| --- | --- | --- |
| 400 | `image_required` | 没有图片 |
| 400 | `invalid_image` | base64/data URL 非法或无法解码 |
| 400 | `invalid_image_source` | 非法 `file:` URL / 路径形式 |
| 400 | `local_image_paths_disabled` | 服务关闭了本地路径读取 |
| 400 | `local_image_outside_root` | 本地路径不在 `local_image_root` 内 |
| 400 | `image_not_found` | 本地文件不存在/不可读/不是普通文件 |
| 400 | `invalid_image_url` | 非 http(s)、带凭据、端口不允许、无法解析 |
| 400 | `private_image_url` | URL 指向私网/loopback（未开启 allow_private） |
| 400 | `unsupported_image_type` | 非图片内容类型 |
| 400 | `image_fetch_failed` | 下载失败/超时 |
| 400 | `invalid_json` | 请求体不是 JSON 对象 |
| 400 | `unsupported_parameter` | `n`、`tools`、`response_format`、未知 part 等 |
| 400 | `too_many_images` | 超过 `max_images` |
| 400 | `batch_too_large` | 超过 `max_batch` |
| 400 | `duplicate_id` | 批量项 id 重复 |
| 401 | `invalid_api_key` | API key 缺失或不匹配 |
| 413 | `image_too_large` | 图片超过 `max_image_bytes` |
| 503 | `server_busy` | 队列满或等待超时 |
| 503 | `not_ready` | 模型未加载完成 |
| 500 | `internal_error` | 推理/内部异常 |

批量接口的项错误不影响 HTTP 状态码（仍为 200）。
