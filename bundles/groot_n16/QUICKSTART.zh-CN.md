# groot_n16 快速上手

<p align="right"><a href="QUICKSTART.md">English</a></p>

**环境**：Linux · NVIDIA **SM120**（Blackwell）· CUDA **13.x** · Python **3.12**  
**权重**：[nvidia/GR00T-N1.6-3B](https://huggingface.co/nvidia/GR00T-N1.6-3B)（不进 zip）

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/groot_n16/dist"   # pack 后用 dist/
```

---

## 1. Build（编译 native + 组装 bundle）

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/groot_n16/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

产物：

- `bundles/groot_n16/lib/*.so` — `flash_rt_kernels`、`flash_rt_fa2`
- `bundles/groot_n16/flash_rt/` — GROOT 最小 Python 子树
- `bundles/groot_n16/.build/manifest-overlay.json`

FlashRT 已编译时可跳过 cmake：

```bash
bash bundles/groot_n16/build.sh --repo-root "$FLASHRT_REPO" --pack-only
```

---

## 2. Pack（生成可分发 dist/）

```bash
bash bundles/groot_n16/pack.sh
# 等价: bash scripts/pack_bundle.sh --bundle-dir bundles/groot_n16
```

产物在 `bundles/groot_n16/dist/`：

- `flashcli-bundle.json`（合并后的权威 manifest）
- `runtime/sm120-cu130-linux-x86_64-py312/*.so`
- `run.py`、`_groot_*.py`、`flash_rt/`

---

## 3. Validate

```bash
flashcli bundle validate bundles/groot_n16/dist
```

---

## 4. 拉权重并运行

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 国内可选

flashcli pull bundles/groot_n16/dist

flashcli run bundles/groot_n16/dist \
  --prompt "pick up the cup on the table" \
  --embodiment-tag gr1 \
  --num-views 1 \
  --image /path/to/rgb.jpg

# 无图冒烟（随机占位帧）:
flashcli run bundles/groot_n16/dist \
  --embodiment-tag gr1 \
  --num-views 1
```

---

## 5. 性能抽测

```bash
flashcli run bundles/groot_n16/dist \
  --embodiment-tag gr1 \
  --num-views 1 \
  --benchmark 5
```

---

## 常见问题

| 现象 | 处理 |
|------|------|
| `GemmRunner missing fp8_nt_dev` | `_groot_compat.py` 自动 shim；仍失败则重编 FlashRT `.so` |
| tokenizer 加载失败 | 确保 checkpoint 含 `tokenizer/`，或预下载 `Qwen/Qwen3-1.7B` |
| 输出像噪声 | 检查 `embodiment_tag` 是否为已训练 tag |
| `num_views` 不匹配 | `gr1` 用 1；`robocasa`/`behavior_r1_pro` 用 3 |
