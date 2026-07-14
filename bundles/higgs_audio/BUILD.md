# Building the Higgs Audio v3 Bundle

## Prerequisites

- FlashRT source tree at `/app/FlashRT` (or pass `--repo-root`)
- NVIDIA GPU SM120 (RTX 5090 / 5060 Ti / Blackwell)
- CUDA 13.0, Python 3.10+, CMake ≥ 3.20

## Local Build

```bash
# Stage .so + flash_rt/ from a pre-built FlashRT tree:
bash bundles/higgs_audio/build.sh --repo-root /app/FlashRT --pack-only

# Validate:
flashcli bundle validate bundles/higgs_audio/

# Run:
flashcli run bundles/higgs_audio/ --text "Hello world" --out test.wav
```

## Bundle Structure

```
higgs_audio/
├── flashcli-bundle.json          # Manifest (engine mode, run_options, weights)
├── run.py                         # RunEngine: load() + predict()
├── build.sh / _bundle_build.sh    # Build & staging
├── pack.sh                        # Pack wrapper
├── README.md / README.zh-CN.md
├── BUILD.md / BUILD.zh-CN.md
├── .gitignore
├── runtime/                       # Build artifact: .so with version tag
│   └── sm120-cu130-linux-x86_64-py310/
│       ├── flash_rt_kernels-d0db114-sm120-cu130-linux-x86_64-py310.so
│       └── flash_rt_fa2-d0db114-sm120-cu130-linux-x86_64-py310.so
└── flash_rt/                      # Build artifact: vendored Python tree
    ├── BUNDLE_VERSION
    └── ... (26 files)
```

## Version Consistency

The `.so` files in `runtime/` and the Python files in `flash_rt/` are both
staged from the same FlashRT commit (recorded in `flash_rt/BUNDLE_VERSION`).
This ensures the compiled kernel symbols match the Python frontend code.

## Pack for Distribution

```bash
bash bundles/higgs_audio/pack.sh --output-dir bundles/higgs_audio/dist
```
