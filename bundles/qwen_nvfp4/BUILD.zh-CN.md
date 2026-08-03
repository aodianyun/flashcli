# qwen_nvfp4 — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export FLASHRT_REPO=/path/to/FlashRT   # 须与 flash_rt/BUNDLE_VERSION、已发布 build.git_commit 同 commit
```

## 1. 编译 native

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

产出：

| 路径 | 作用 |
|------|------|
| `flash_rt/` | FlashRT Python（与 `.so` 同 commit） |
| `flash_rt/BUNDLE_VERSION` | FlashRT commit / abi 锁定 |
| `lib/*.so` | 矩阵暂存 |
| `runtime/<env-key>/*.so` | 本机加载路径（如 `sm121-cu130-linux-aarch64-py312`） |
| `.build/manifest-overlay.json` | `build.git_commit` + 扫描得到的 `runtime` map |

支持本机探测到的 SM（如 **SM120**、**SM121**/GB10）；NVFP4 通常在 `flash_rt_kernels` 内（独立 `flash_rt_fp4` 可选）。不支持的架构由 FlashRT CMake 失败，脚本不做 SM 白名单拦截。

## 2. 打包（可运行的 `dist/`）

```bash
bash bundles/qwen_nvfp4/pack.sh --repo-root "$FLASHRT_REPO"
# 或一键矩阵发布构建：
bash bundles/qwen_nvfp4/release.sh --clean

export BUNDLE="$(pwd)/bundles/qwen_nvfp4/dist"
flashcli bundle validate "$BUNDLE"
```

`pack.sh`（相对裸调 `pack_bundle.sh`）：

- 按需把 `lib/` 镜像到 `runtime/<env-key>/`
- 保证存在 `flash_rt/BUNDLE_VERSION`
- 本机 cell 与 `release-matrix.env` 不一致时自动 `--skip-matrix-verify`（如 SM121 / aarch64）
- 合并 overlay 写入 `dist/flashcli-bundle.json`，**`dist/` 可直接跑**
- 打包后检查 kernels 与版本锁定

`pull` / `run` / `serve` 请用 **`dist/`**（源树作者 manifest 可能只有官方 SM120×x86_64 cell）。

## 3. 拉取权重

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 国内可选

flashcli pull "$BUNDLE@qwen3"
flashcli pull "$BUNDLE@qwen36"
```

## 4. 冒烟 — run

```bash
flashcli run "$BUNDLE@qwen3" --prompt "你好" --max-tokens 64
flashcli run "$BUNDLE@qwen36" --prompt "你好" --max-tokens 64 --K 6
```

## 5. 冒烟 — serve

```bash
flashcli serve "$BUNDLE@qwen3" --host 127.0.0.1 --port 8000

curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3","messages":[{"role":"user","content":"你好"}],"max_tokens":64,"stream":true}'

curl -s http://127.0.0.1:8000/health | jq
```

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| `flash_rt_fp4 … missing (sm != 120)` | 旧脚本逻辑；当前已将 `flash_rt_fp4` 视为可选 |
| `ImportError: flash_rt_kernels` | 重跑 `build.sh` / `pack.sh`；确认 `dist/runtime/<env-key>/` |
| pack 报 `Missing flash_rt/` | 须等 `build.sh` 完整结束（会 stage `flash_rt/` + `BUNDLE_VERSION`） |
| FlashRT 版本错位 | 对齐 `BUNDLE_VERSION` ↔ `build.git_commit` ↔ FlashRT checkout |
| FlashHub runtime 过旧 | 本地重编；使用 `bundles/qwen_nvfp4/dist@qwen36` |
| `max_tokens must be <= N` | 提高 qwen36 serve 的 `--max-output-tokens` |
