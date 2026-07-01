# pi05_libero

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong> · <a href="QUICKSTART.zh-CN.md">快速上手</a></p>

Pi0.5 LIBERO VLA，权重 [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044)。

**Ref**：`flashcli-bundle/pi05_libero:1.0.4`。用户通过 FlashHub sync runtime；flashcli 按本机 GPU + CUDA 匹配 manifest 中的 `runtime` env key，并从 `runtime/<env-key>/` 加载 `.so`。可用 `flashcli models envs flashcli-bundle/pi05_libero:1.0.4` 查看本机环境键是否匹配。

## 运行所需文件（sync 后 bundle 根）

```text
flashcli-bundle.json
run.py                    # script entry (main)
run_engine.py             # engine entry (RunEngine); see flashcli-bundle.engine.json
_pi05_infer.py
_pi05_compat.py
flash_rt/
runtime/<env-key>/         # 本机 env 的 *.so
```

权重由 flashcli 下载到 `~/.flashcli/models/pi05_libero/1.0.4/checkpoint/`，**不**打进 bundle。

## Entry 模式

| 文件 | 说明 |
|------|------|
| `flashcli-bundle.json` | **默认 script**：`run.main(argv)`，**不** `import flashcli_bundle` |
| `flashcli-bundle.engine.json` | **engine 示例**：`run_engine.RunEngine`；本地试 engine 时可 `cp flashcli-bundle.engine.json flashcli-bundle.json` |

`run.py`（script）与 `run_engine.py`（engine）共用 `_pi05_infer.py`；script 仅从 `FLASHCLI_CHECKPOINT` 等环境变量读路径。

## 用户

命令速查见 **[QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md)**。

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
flashcli run flashcli-bundle/pi05_libero:1.0.4 --prompt "..." --image /path/to/base.jpg
```

## 排错

### HuggingFace 权重下载失败（`LocalEntryNotFoundError`）

bundle 仅含 runtime；约 7.5GB 权重需从 Hub 拉取。K8s/内网若无法访问 `huggingface.co` 与 `hf-mirror.com`，会报此错误（多为网络/DNS/代理，而非仓库不存在）。

flashcli 下载权重与官方 CLI 相同：设置 `HF_ENDPOINT` 后调用 `hf download`（或 `huggingface-cli download`）。**请先** `export HF_ENDPOINT=https://hf-mirror.com`，再执行 `flashcli pull/run`。

```bash
# 诊断：用 GET（不要用 curl -I / HEAD，镜像可能对 HEAD 返回 308）
curl -fsSL 'https://hf-mirror.com/api/models/lerobot/pi05_libero_finetuned_v044/revision/main' | head -c 80

# 1) 清理不完整缓存后重试
rm -rf ~/.flashcli/models/*/checkpoint

# 2) 与 hf download 相同：在启动 flashcli 之前 export
export HF_ENDPOINT=https://hf-mirror.com
# 未设置 HF_ENDPOINT 时默认先试官方 Hub，失败再试镜像；仅镜像优先：export FLASHCLI_PREFER_HF_MIRROR=1

flashcli pull flashcli-bundle/pi05_libero:1.0.4
# 或带本地 bundle：
flashcli run bundles/pi05_libero --image /path/to.jpg
```

有代理时设置 `HTTPS_PROXY` / `HTTP_PROXY`。也可在能联网的机器预下载后拷贝：

```bash
huggingface-cli download lerobot/pi05_libero_finetuned_v044 \
  --local-dir ./checkpoint

flashcli run bundles/pi05_libero \
  --checkpoint ./checkpoint --image /path/to.jpg
```

本地 dev：positional ref 须为含 `flashcli-bundle.json` 的目录（如 `bundles/pi05_libero` 或 `bundles/pi05_libero/dist/`）。

### `no kernel image is available for execution on the device`

多为 **GPU/CUDA 格不匹配** 或 **FlashHub runtime 过旧**。执行 `flashcli models envs flashcli-bundle/pi05_libero:1.0.4`，应匹配 `sm89-cu124-*`、`sm89-cu130-*` 或 `sm120-cu130-*`。

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

SM89：`_pi05_compat.py` 提供 shim，或重新 build 含 `fp8_nt_dev` 的 FlashRT。

### `FvkContext is already registered`

使用最新 flashcli；内核在 `run.py` 加载流程中只注册一次。
