# variants/ 布局（git ref = 版本）

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

每个 **git ref**（branch 或 tag）对应仓库的一次完整快照。  
该 ref 下按 GPU 环境使用**扁平**目录（无 `1.0.0/` semver 子目录）：

```text
variants/
├── sm89-cu124-linux-x86_64/
│   ├── flashcli-bundle.json
│   ├── partner/              # 可选；通常已打入 runtime/python/partner/
│   └── runtime/
└── sm120-cu128-linux-x86_64/
    ├── flashcli-bundle.json
    └── runtime/
```

发布冻结版本：

```bash
git tag bundle-1.1.0
# models.yaml: bundle.git.ref: bundle-1.1.0
```

CLI：`flashcli run my-model --bundle-ref bundle-1.1.0`
