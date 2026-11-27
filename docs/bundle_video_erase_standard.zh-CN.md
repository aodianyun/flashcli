# MiniMax-Remover 视频擦除服务规范（flashcli serve）

<p align="right"><a href="bundle_video_erase_standard.md">English</a> · <strong>简体中文</strong></p>

> **类别补充。** 通用的 manifest、目录布局、权重、运行时与发布规则仍以
> [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)（英文版：
> [bundle_publish_standard.md](bundle_publish_standard.md)）为准。本页只补充视频擦除 API 的要求。
>
> **网关透传。** 视频擦除 bundle 使用 `format_version: 4`、engine 模式、`ServeEngine`，并通过
> `register_routes(app)` 提供原生 `/v1/video/erase` 系列路由。它还会覆盖注册 `/v1/chat/completions` 和
> `/v1/responses`，以加入 `erase` 扩展和进度 SSE；这些覆盖路由优先于 host 默认路由，并自行负责解析/SSE/错误
> 形状。host 基础路由仍由 host 持有。flashserver `/v1` 网关会把这些路径（包括任务/文件 URL）透传到模型
> serve 端点。body 不带 `model` 的自定义路径用 `?model=<full-ref>` 选择模型，见
> [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md) §1.2。
>
> **通用规则不重复。** manifest/目录/entry/运行时/权重/发布规则见
> [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)；engine 模式的 host 行为
> （标准路由、鉴权、并发、请求日志、SSE 传输、错误转换）见
> [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)。本文只补充视频擦除路由、schema、限制和验收。

本文是 **MiniMax-Remover FlashRT bundle 的服务端规范**，同时定义：

1. 面向视频擦除（mask-guided video inpainting / object、字幕、水印移除）的
   **原生 HTTP API**；
2. 在 **OpenAI Chat Completions / Responses** 上的 **`erase` 扩展规范**。

适用实现：`aodianyun/MiniMax-Remover:1.0.4`（FlashRT `4ad99bd3`），
`flashcli serve` engine 模式。API 版本：`video.erase` v1。

---

## 1. 定位

MiniMax-Remover 是 **mask 引导**的视频修复模型：输入一段视频（或帧序列）与
逐帧/静态二值 mask，输出与输入等长的、mask 区域被补全的视频帧。模型不接受
文本指令，移除区域完全由 mask 决定；`prompt` 字段仅为协议兼容而接受，不参与
计算。

服务模式与 OCR / LLM bundle 的差异：

| 维度 | OCR / LLM | 本服务 |
|---|---|---|
| 输入 | 单张图片 / 文本 | 视频、帧序列、帧压缩包 + mask 视频/图片/序列 |
| 计算 | 单次前向 / token 生成 | 12 步 flow-matching + VAE，单卡数十秒 |
| 输出 | JSON 文本 | 帧目录、ZIP、MP4 或 base64 帧 |
| 流式 | token / 行增量 | 阶段进度（queued → media → inference → encode） |
| 校准 | 无 | 首次真实请求按形状在线校准 + 图捕获 |

---

## 2. 架构与 host 边界

engine 模式下 host 构建 FastAPI，并负责基础路由、鉴权、请求日志和进程生命周期；host 调用 `ServeEngine.register_routes(app)`，视频擦除 bundle 注册原生 `/v1/video/erase*` 路由，并**覆盖** `/v1/chat/completions` / `/v1/responses` 以加入 `erase` 扩展和进度 SSE；这些覆盖路由优先，并自行负责解析/SSE/错误形状。声明 `openai.chat` 和 `openai.responses` 让网关路由这些覆盖路径；只有同时实现标准视频路由时才声明 `openai.videos`。host 契约见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)；本文只补充视频擦除路由、媒体契约、任务和限制。

## 3. 启动与生命周期

host 负责模型加载/预热、就绪判定和 serve 生命周期，见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)。bundle 只实现 `ServeEngine.load` / `warmup` 和擦除处理函数。

## 4. 鉴权与通用约定

host 负责鉴权、并发门、请求日志和 JSON 错误信封，见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)。视频擦除的媒体限制、输出规则和安全校验属于分类专有内容，见 §5 与 §13–§15。

## 5. 媒体输入规范

所有媒体字段（`video`、`frames`、`mask`、`masks`、`frames_archive`）接受同一组
来源写法：

| 写法 | 示例 |
|---|---|
| data URL | `data:video/mp4;base64,...`、`data:image/png;base64,...`、`data:application/zip;base64,...` |
| 裸 base64 | PNG/JPEG/MP4/ZIP 字节的 base64 |
| HTTP(S) | `https://example.com/clip.mp4`（默认拒绝私网/回环，见 §15） |
| 本地路径 | `/data/clips/tennis/` 下的文件路径、相对路径、`~/...` |
| `file://` | `file:///data/clips/mask.png` |

也可用对象形式显式指定：

```json
{"url": "https://..."}
{"path": "/data/..."}
{"base64": "..."}
{"data_url": "data:video/mp4;base64,..."}
```

### 5.1 视频源

- `video`：一个视频容器（MP4/MOV/WebM/MKV/AVI/MPEG/TS）。用镜像内的 ffmpeg
  解码为 RGB 帧；`fps` 从容器读取。
- `frames`：帧列表（按数组顺序）或单个 ZIP/视频/图片。列表元素可以是图片、
  ZIP 或短视频；ZIP 内图片按数字文件名排序（`00000.png`、`1.jpg` 等），
  非数字名按字典序。
- `frames_archive` / `archive`：显式 ZIP 帧包。ZIP 内可含 `frames/` 子目录。
- `video` 与 `frames`/`frames_archive` 互斥。

### 5.2 Mask 源

| 字段 | 形式 | 语义 |
|---|---|---|
| `mask` | 图片 / 视频 / ZIP | 图片 = 静态 mask（广播到所有帧）；视频/ZIP = 逐帧 mask |
| `mask_video` | 视频 / ZIP / 图片 | 逐帧 mask 的显式写法 |
| `masks` | 图片/视频/ZIP 的列表 | 列表长度为 1 时视为静态；≥ 帧数时截断；不足部分按全黑（不擦除） |

- mask 为 8-bit 灰度；`> mask_threshold`（默认 127）为移除区域。
- mask 尺寸与帧不一致时用最近邻缩放到帧尺寸。
- mask 帧数少于输入帧数时，剩余帧视为无移除区域；多于输入帧数时忽略多余帧。
- 所有 mask 均为空时不执行推理，直接输出源帧（`mask.has_region=false`）。

### 5.3 帧率与尺寸

- 视频输入：`input.fps` 来自容器；帧序列输入默认 24 fps（可用
  `output.fps` 覆盖）。
- 所有帧统一到第一帧尺寸（不一致时双线性缩放）。
- `options.width` / `options.height`（必须同时给出）在推理前缩放；内部 pad 到
  16 的倍数，输出裁回工作尺寸。
- 尾帧：Wan VAE 解码 4k+1 帧，超出输入帧数的解码帧被丢弃，不足的尾帧直接使用
  源帧，保证输出帧数 = 输入帧数。

---

## 6. 原生 API：`POST /v1/video/erase`

### 6.1 JSON 请求

```json
{
  "model": "minimax_remover",
  "video": "data:video/mp4;base64,...",
  "mask": "data:image/png;base64,...",
  "options": {
    "num_inference_steps": 12,
    "iterations": 6,
    "seed": 42,
    "max_frames": 0,
    "width": 0,
    "height": 0,
    "mask_threshold": 127
  },
  "output": {"format": "frames", "fps": 0, "crf": 18},
  "async": false
}
```

帧序列写法：

```json
{
  "frames": ["data:image/png;base64,...", "..."],
  "masks": ["data:image/png;base64,...", "..."],
  "output": {"format": "zip"}
}
```

### 6.2 multipart/form-data

同一端点接受文件上传，便于 `curl`：

```bash
curl -s http://127.0.0.1:8080/v1/video/erase \
  -H "Authorization: Bearer sk-xxx" \
  -F video=@clip.mp4 -F mask=@mask.png \
  -F 'output={"format":"frames"}'
```

字段：`video`、`mask`、`mask_video`、`frames`（可重复）、`masks`（可重复）、
`frames_archive`、`options`（JSON 字符串）、`output`（JSON 字符串）、`async`、
`model`、`prompt`。上传文件保存在 `output_root/_uploads/`，任务结束后删除。

### 6.3 同步响应（200）

```json
{
  "object": "video.erase.result",
  "version": 1,
  "job_id": "erase-0123456789abcdef",
  "status": "completed",
  "model": "minimax_remover",
  "engine": "flashrt-minimax-remover",
  "route": "fp8-nvfp4-graph",
  "precision": "fp8+nvfp4",
  "device": "NVIDIA GeForce RTX 5060 Ti",
  "input": {"kind": "video", "width": 432, "height": 240,
            "frames": 70, "fps": 24.0, "bytes": 1234567},
  "mask": {"mode": "image", "static": true, "frames": 70,
           "has_region": true, "region_fraction": 1.0, "threshold": 127},
  "options": {"num_inference_steps": 12, "iterations": 6, "seed": 42,
              "max_frames": 0, "width": 0, "height": 0,
              "mask_threshold": 127},
  "output": {"format": "frames", "fps": 24.0, "frame_count": 70,
             "width": 432, "height": 240,
             "frames": [{"index": 0, "filename": "000000.png",
                          "url": "/v1/video/erase/files/<job>/frames/000000.png"}],
             "zip_url": null, "mp4_url": null},
  "timing": {"queue_ms": 0.2, "media_ms": 380.1, "inference_ms": 3120.4,
             "encode_ms": 240.8, "e2e_ms": 3741.5},
  "memory": {"peak_allocated_gib": 2.78, "peak_reserved_gib": 3.10},
  "prompt": null
}
```

### 6.4 异步响应（202）

请求带 `"async": true` 时立即返回：

```json
{
  "object": "video.erase.job",
  "id": "erase-0123456789abcdef",
  "job_id": "erase-0123456789abcdef",
  "status": "queued",
  "created_at": 1795079000,
  "queue_s": null,
  "cancel_requested": false
}
```

之后轮询 `GET /v1/video/erase/jobs/{job_id}`；完成后同一对象携带完整结果。

---

## 7. 任务 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/v1/video/erase` | `async=false` 同步执行；`async=true` 返回 202 + job |
| `GET` | `/v1/video/erase/jobs` | 最近任务列表（`?limit=N`，默认 50） |
| `GET` | `/v1/video/erase/jobs/{job_id}` | 任务状态；完成时含完整结果 |
| `GET` | `/v1/video/erase/jobs/{job_id}/result` | 结果别名；失败时返回原始错误状态 |
| `DELETE` | `/v1/video/erase/jobs/{job_id}` | 已完成任务：删除记录与输出；运行中：请求取消 |
| `GET` | `/v1/video/erase/files/{job_id}/{path}` | 下载帧 / ZIP / MP4 / result.json |
| `GET` | `/v1/video/erase/info` | 能力、限制、默认值、运行时状态 |

任务状态：`queued` → `running` → `completed` | `failed` | `cancelled`。

- 取消：排队中的任务立即取消；**运行中的 CUDA Graph 不能中途打断**，任务会
  跑完并保留结果，响应中标记 `cancel_requested=true`。
- 同步请求超过 `request_timeout_sec`（默认 900 s）返回 504，任务继续在后台运行，
  可用 job id 轮询或删除。
- 已完成任务的输出保留 `output_retention_sec`（默认 3600 s），且最多保留
  `max_jobs`（默认 64）条记录；超出时删除最旧的已完成任务及其目录。

---

## 8. 输出格式

`output.format`：

| 值 | 产物 | 响应字段 |
|---|---|---|
| `frames`（默认） | `<job>/frames/%06d.png` | `output.frames[].url` |
| `zip` | `<job>/output.zip`（`frames/%06d.png` + `result.json`） | `output.zip_url` |
| `mp4` | `<job>/output.mp4`（H.264，`libx264`，`-movflags +faststart`） | `output.mp4_url` |
| `base64` | 不落盘；PNG 帧内联为 base64 | `output.frames[].content_base64` |
| `none` | 仅返回元数据 | — |

- `output.fps`：MP4 帧率；0 = 输入视频 fps，帧序列默认 24。
- `output.crf`：x264 CRF（0–51，默认 18）；`output.quality` 1–10 可作为替代。
- MP4 宽高为奇数时用边缘复制 pad 到偶数（yuv420p 要求）。
- `base64` 总 PNG 字节数受 `max_inline_bytes`（默认 32 MiB）限制；超出返回 413，
  建议改用 `zip`/`frames`。
- 所有下载路径都限制在任务目录内（路径穿越返回 400）。

---

## 9. OpenAI 扩展：Chat Completions

`POST /v1/chat/completions` 在标准 OpenAI 视觉消息格式上扩展：

- **视频 part**：`{"type": "video_url", "video_url": {"url": "<媒体源>"}}`
  （别名：`video`、`input_video`）。
- **mask part**：`{"type": "mask_image" | "mask_url" | "video_mask", ...}`。
- **`image_url` part**：当同一条请求已有视频源时，作为 mask 使用：1 张 = 静态
  mask；多张 = 按顺序的逐帧 mask。这样标准 OpenAI 视觉客户端无需私有 part 即可
  传入 mask。
- 文本 part 作为 `prompt` 接受但不参与计算。
- `tools` / `functions` / `n>1` 返回 400（本模型不生成 token）。

### 9.1 `erase` 扩展对象（请求）

```json
{
  "erase": {
    "mask": "<媒体源>",            // 与 content 里的 mask part 二选一
    "mask_video": "<媒体源>",
    "masks": ["<媒体源>", "..."],
    "frames": "<ZIP 或帧列表源>",  // 也可用 content 里的 video_url
    "options": {"num_inference_steps": 12, "iterations": 6, "seed": 42,
                 "max_frames": 0, "width": 0, "height": 0,
                 "mask_threshold": 127},
    "output": {"format": "frames", "fps": 0, "crf": 18},
    "content_format": "text",      // text | json
    "async": false
  }
}
```

也接受 `extra_body.erase`（OpenAI Python SDK 写法）。

### 9.2 响应

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "minimax_remover",
  "choices": [{"index": 0,
    "message": {"role": "assistant",
                "content": "Erased the masked region from 70 frame(s) ..."},
    "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "erase": {"object": "video.erase.result", "...": "同 §6.3"}
}
```

- `content` 默认是摘要文本；`erase.content_format=json` 或
  `response_format={"type":"json_object"}` 时是 `erase` 对象的 JSON 字符串。
- 结构化结果始终在顶层 `erase`；客户端应读该对象而不是解析文本。
- `async=true` 时返回普通 `chat.completion`，`erase` 为 job 快照
  （`object: video.erase.job`）。

### 9.3 Python SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="sk-xxx")
resp = client.chat.completions.create(
    model="minimax_remover",
    messages=[{"role": "user", "content": [
        {"type": "video_url", "video_url": {"url": video_data_url}},
        {"type": "image_url", "image_url": {"url": mask_data_url}},
    ]}],
    extra_body={"erase": {"output": {"format": "zip"}}},
)
print(resp.model_extra["erase"]["output"]["zip_url"])
```

---

## 10. OpenAI 扩展：Responses

`POST /v1/responses`：

- `input` 为字符串或 item 列表；
- `input_text` / `message.content` 的 `input_text` 作为 prompt；
- `input_video` / `video_url` item（或 message content part）为视频源；
- `input_image` / `image_url` / `input_mask` item 为 mask（语义同 §9）；
- `erase` 扩展对象同 §9.1；
- `previous_response_id`、`tools` 返回 400（无状态、无工具）。

响应为标准 `response` 对象，额外顶层 `erase`；`output_text` 同 §9.2 的
`content`。

---

## 11. 流式（SSE）

`stream: true` 时：

- Chat Completions：`chat.completion.chunk` 序列；每个进度块带
  `erase: {object: "video.erase.progress", phase, ...}`，最终块带
  `finish_reason: "stop"`、`usage`（若 `stream_options.include_usage`）和完整
  `erase` 结果，随后 `data: [DONE]`。
- Responses：`response.created` / `response.in_progress` /
  `response.erase.progress` / `response.output_text.*` /
  `response.completed` 事件。

阶段：

| phase | 含义 |
|---|---|
| `queued` | 已入队 |
| `running` | worker 开始执行 |
| `media` | 解码视频/帧、加载 mask |
| `inference` | 校准/图捕获/CUDA Graph replay |
| `inference_done` | 推理完成（带耗时与显存） |
| `encode` | 打包输出 |
| `completed` / `failed` / `cancelled` | 终态 |

客户端断开：排队中的任务被取消；运行中的任务继续跑完（GPU 不可中断），结果保留
可轮询。

---

## 12. 错误码

| HTTP | code | 说明 |
|---|---|---|
| 400 | `video_required` | 缺少视频/帧源 |
| 400 | `mask_required` | 缺少 mask |
| 400 | `unsupported_parameter` | tools / n>1 / 未知选项 |
| 400 | `invalid_video` / `invalid_image` / `invalid_archive` | 解码失败 |
| 400 | `invalid_media_url` / `private_media_url` | URL 非法 / SSRF 拦截 |
| 400 | `local_media_paths_disabled` / `local_media_outside_root` | 本地路径策略 |
| 401 | `invalid_api_key` | 鉴权失败 |
| 404 | `job_not_found` / `file_not_found` | 任务/文件不存在 |
| 413 | `media_too_large` / `frames_limit_exceeded` / `pixels_limit_exceeded` / `inline_limit_exceeded` | 超出限制 |
| 503 | `server_busy` / `not_ready` | 队列满 / 未加载 |
| 504 | `request_timeout` | 同步等待超时（任务继续） |
| 500 | `internal_error` | 推理失败（含 CUDA OOM） |

---

## 13. 限制与默认值

`GET /v1/video/erase/info` 返回运行时实际值。serve 选项：

| 选项 | 默认 | 说明 |
|---|---|---|
| `--model-name` | `minimax_remover` | 响应中的模型 id |
| `--api-key` | 空 | `/v1/*` 鉴权 |
| `--device` | `cuda:0` | CUDA 设备 |
| `--attention` | `auto` | 内置 SageAttention-2；显式 `FLASHRT_ATTN_MODE` |
| `--step-cache` | `auto` | 0/3/7/11 四步缓存；`none` 或步号列表 |
| `--max-queue` | 32 | 等待 GPU 的请求/任务上限；超出 503 |
| `--request-timeout-sec` | 900 | 同步请求等待上限；超时 504 |
| `--max-frames` | 121 | 单段帧数上限；413 以上 |
| `--max-pixels` | 0 | 工作分辨率像素上限；0 = 自动（≥15 GiB 卡 399360，12 GiB 卡 103680） |
| `--max-video-bytes` | 256 MiB | 视频/mask 视频源大小 |
| `--max-image-bytes` | 20 MiB | 单图/单帧 |
| `--max-archive-bytes` | 512 MiB | ZIP 解压后总量 |
| `--max-inline-bytes` | 32 MiB | base64 输出总量 |
| `--max-graphs` | 4 | 常驻 CUDA Graph 形状数 |
| `--max-jobs` | 64 | 保留的已完成任务数 |
| `--output-root` | `<tmp>/minimax_remover_serve` | 任务输出根目录 |
| `--output-retention-sec` | 3600 | 输出保留秒数（0 = 仅受 max_jobs 限制） |
| `--public-base-url` | 空 | 输出 URL 的绝对前缀 |
| `--default-steps` | 12 | 默认 denoise 步数 |
| `--default-iterations` | 6 | 默认 mask 膨胀次数 |
| `--default-seed` | 42 | 默认 latent seed |
| `--default-output-format` | `frames` | 默认输出格式 |
| `--mask-threshold` | 127 | 默认 mask 阈值 |
| `--allow-private-media-urls` | false | 允许私网 URL（SSRF 防护） |
| `--media-url-timeout-sec` | 15 | URL 下载超时 |
| `--media-url-ports` | `80,443` | 允许的 URL 端口（空 = 任意） |
| `--allow-local-media-paths` | true | 允许本地路径 / `file://` |
| `--local-media-root` | 空 | 本地路径沙箱根目录 |

请求级 `options` 可覆盖 `num_inference_steps`、`iterations`、`seed`、
`max_frames`（截断）、`width`/`height`、`mask_threshold`；`step_cache` 与
`attention` 只能启动时设置。

---

## 14. 精度、性能与显存

测试协议（每轮相同数据）：DAVIS `tennis` 70 帧 / `bmx-trees` 80 帧，
432x240，12 步，`iterations=6`，seed 42；E2E 为校准/捕获后 5 次回放的中位数；
显存峰值来自 PyTorch allocator。基线为同机同数据的 fp16 diffusers 实现。

| GPU | 路线 | 基线 E2E | FlashRT E2E | 加速比 | 峰值显存 | cosine 均值/最小 | PSNR |
|---|---|---:|---:|---:|---:|---|---:|
| RTX 5060 Ti 16 GB | `fp8-nvfp4-graph` | 16.86 s | **3.12 s** | **5.40×** | 2.78 GiB | 0.9988 / 0.9977 | 31.84 dB |
| RTX 4060 Ti 16 GB | `fp8-graph` | 20.94 s | **4.03 s** | **5.20×** | 4.03 GiB | 0.9995 / 0.9984 | 33.91 dB |
| RTX 3060 12 GB | `int8-graph` | 27.27 s | **6.27 s** | **4.35×** | 3.89 GiB | 0.9996 / 0.9994 | 38.07 dB |

832x480 生产形状（RTX 5060 Ti）：基线 99.26 s → **21.88 s**（4.54×），
峰值 alloc 7.24 GiB / NVML 11.03 GiB；RTX 4060 Ti：118.54 s → 24.64 s
（4.81×），峰值 alloc 8.99 GiB / NVML 12.48 GiB。

### 14.1 `flashcli serve` 实测（同一 tennis 70 帧数据）

| GPU | 路线 | 首请求 E2E（校准+捕获，none） | 稳态 inference | 稳态 E2E（none） | 稳态 E2E（frames 输出） | 稳态峰值显存 | NVML 峰值 | 与 run 输出 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| RTX 5060 Ti 16 GB | `fp8-nvfp4-graph` | 13.78 s | 3.108 s | 3.33 s | 3.78 s | 2.74 GiB | 4285 MiB | 逐像素一致 |
| RTX 4060 Ti 16 GB | `fp8-graph` | 19.07 s | 4.04–4.07 s | 4.24–4.26 s | 4.72 s | 3.41 GiB | 4832 MiB | 逐像素一致 |
| RTX 3060 12 GB | `int8-graph` | 47.28 s | 6.34 s | 6.54 s | 7.03 s | 2.08 GiB | 3619 MiB | 逐像素一致 |

- 首请求包含在线量化校准 + CUDA Graph 捕获；`none` 输出不含 PNG 打包。
- 稳态 `inference_ms` 与 `flashcli run` 的中位数一致（差 < 1%）；serve 的额外 E2E
  是 HTTP/JSON、ZIP 解码与输出打包（~0.2 s + 编码）。
- 与 run 路径对比使用同一份 lossless 帧 ZIP / mask ZIP 和 seed；解码后的像素
  逐帧完全一致（cos=1.0, PSNR=99）；PNG 文件 md5 因压缩级别不同而不同。

完整逐轮优化记录见优化 campaign `rsi-task-170` 的 `docs/round_table.md`
（`/data/inference-campaigns/rsi-task-170`）与 FlashHub 上的报告。服务模式的额外开销是 HTTP 编解码、视频解码/编码与 PNG/ZIP
打包；`timing` 字段把它与 `inference_ms` 分开，便于定位。

---

## 15. 安全

- 默认只允许 `http`/`https` 的公网地址；解析到 loopback/私网/链路本地地址的
  URL 直接 400（可显式 `--allow-private-media-urls true` 放开）。
- URL 端口默认限制 80/443；最多 4 次重定向，每一跳重新校验。
- 本地路径默认允许（驻留服务场景）；生产部署建议设置
  `--local-media-root /data/media` 限制可读目录，或
  `--allow-local-media-paths false` 完全关闭。
- 上传/下载大小、帧数、像素数、ZIP 解压总量都有硬上限。
- 输出下载路径做任务目录逃逸校验。

---

## 16. 兼容性说明

- 本服务是**视频擦除模型**，不是 LLM：不提供 token 生成、工具调用、推理通道、
  Anthropic Messages API。`/v1/completions` 返回 400 并指向支持的端点。
- `usage` 字段保留 OpenAI 形状但为 0；真实计时在 `erase.timing`。
- 一个 bundle 覆盖 SM86 / SM89 / SM120；不支持 A100/H100/Hopper。
- 版本 `1.0.4` 起提供 serve；`flashcli run` 的 CLI 与 1.0.3 一致。

---

## 相关文档

- [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) —— manifest、目录布局、权重与发布
- [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md) —— engine 模式 `ServeEngine`、capability 与 `register_routes`
- [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) —— `entry.kind` 执行 backend
