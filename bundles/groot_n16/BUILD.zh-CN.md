# groot_n16 — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. 编译

```bash
bash bundles/groot_n16/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

产物：`runtime/sm120-cu130-linux-x86_64-py312/*.so`、`flash_rt/`、`.build/manifest-overlay.json`

FlashRT 已编译时可跳过 cmake：

```bash
bash bundles/groot_n16/build.sh --repo-root "$FLASHRT_REPO" --pack-only
```

## 2. 打包

```bash
bash bundles/groot_n16/pack.sh
export BUNDLE="$(pwd)/bundles/groot_n16/dist"
```

## 3. 校验

```bash
flashcli bundle validate "$BUNDLE"
```

## 4. 冒烟测试

`flashcli pull` 会下载 GR00T 权重与 Qwen3 tokenizer（`checkpoint/tokenizer/`）。

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 国内可选

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "pick up the cup on the table" \
  --embodiment-tag gr1 \
  --num-views 1 \
  --image /path/to/rgb.jpg

flashcli run "$BUNDLE" --embodiment-tag gr1 --num-views 1

flashcli run "$BUNDLE" --embodiment-tag gr1 --num-views 1 --benchmark 5
```

确认 tokenizer：

```bash
ls "$(flashcli models show "$BUNDLE" 2>/dev/null | sed -n 's/.*checkpoint: //p')/tokenizer/"
```

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| `GemmRunner missing fp8_nt_dev` | 重编 FlashRT 或 `_groot_compat.py` shim |
| tokenizer 加载失败 | 重新 `flashcli pull`；`checkpoint/tokenizer/` 需 4 个文件 |
| 输出像噪声 | `embodiment_tag` 或 `--num-views` 不匹配 |
