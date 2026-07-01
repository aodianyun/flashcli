# groot_n16

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong> · <a href="QUICKSTART.zh-CN.md">快速上手</a></p>

GROOT N1.6 VLA；权重 [nvidia/GR00T-N1.6-3B](https://huggingface.co/nvidia/GR00T-N1.6-3B)。

**GPU**：NVIDIA **SM120**（Blackwell）· CUDA **13.x** · Python **3.12**

## 推理所需文件（sync 后）

```text
flashcli-bundle.json
run.py
_groot_infer.py
_groot_compat.py
flash_rt/
runtime/sm120-cu130-linux-x86_64-py312/   # 本机 *.so
```

权重由 flashcli 下载到 `~/.flashcli/models/groot_n16/.../checkpoint/`，不进 zip。

## 入口

`flashcli-bundle.json` 为 **script 模式**：`run.main(argv)`，不 `import flashcli_bundle`。权重路径由 `FLASHCLI_CHECKPOINT` 注入（`flashcli run` 设置）。

默认 embodiment：**`gr1`**（1 路相机）。基座 checkpoint 中其它已训练 tag：`robocasa_panda_omron`（3 路）、`behavior_r1_pro`（3 路）。

## 用户

详见 **[QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md)**（build / pack / run）。

## 常见问题

| 现象 | 处理 |
|------|------|
| HuggingFace 下载失败 | 设 `HF_ENDPOINT=https://hf-mirror.com`，或预下载后 `--checkpoint` |
| 输出像噪声 | 使用已训练 `embodiment_tag`（`gr1` / `robocasa_panda_omron` / `behavior_r1_pro`） |
| `num_views` 不匹配 | `gr1` → 1 路；`robocasa_panda_omron` / `behavior_r1_pro` → 3 路 |
| tokenizer 加载失败 | 先执行 `flashcli pull`（自动下载到 `checkpoint/tokenizer/`）；或检查 HF 网络 |
| `'GemmRunner'... fp8_nt_dev` | 重编 FlashRT，或 bundle 内 `_groot_compat.py` shim |
