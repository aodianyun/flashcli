# 构建 Higgs Audio v3 Bundle

## 前提条件

- FlashRT 源码树位于 `/app/FlashRT`（或通过 `--repo-root` 指定）
- NVIDIA GPU SM120 (RTX 5090 / 5060 Ti / Blackwell)
- CUDA 13.0, Python 3.10+, CMake ≥ 3.20

## 本地构建

```bash
# 从已编译的 FlashRT 树 staging .so + flash_rt/：
bash bundles/higgs_audio/build.sh --repo-root /app/FlashRT --pack-only

# 校验：
flashcli bundle validate bundles/higgs_audio/

# 运行：
flashcli run bundles/higgs_audio/ --text "你好世界" --out test.wav
```

## Bundle 结构

```
higgs_audio/
├── flashcli-bundle.json          # 清单（engine 模式、run_options、权重配置）
├── run.py                         # RunEngine: load() + predict()
├── build.sh / _bundle_build.sh    # 构建与 staging
├── pack.sh                        # 打包包装
├── README.md / README.zh-CN.md
├── BUILD.md / BUILD.zh-CN.md
├── .gitignore
├── runtime/                       # 构建产物：带版本标签的 .so
│   └── sm120-cu130-linux-x86_64-py310/
│       ├── flash_rt_kernels-d0db114-sm120-cu130-linux-x86_64-py310.so
│       └── flash_rt_fa2-d0db114-sm120-cu130-linux-x86_64-py310.so
└── flash_rt/                      # 构建产物：vendored Python 树
    ├── BUNDLE_VERSION
    └── ... (26 个文件)
```

## 版本一致性

`runtime/` 中的 `.so` 文件和 `flash_rt/` 中的 Python 文件均来自同一个
FlashRT commit（记录在 `flash_rt/BUNDLE_VERSION` 中），确保编译的内核符号
与 Python 前端代码一致。

## 打包发布

```bash
bash bundles/higgs_audio/pack.sh --output-dir bundles/higgs_audio/dist
```
