# variants/ layout (git ref = version)

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Each **git ref** (branch or tag) is one full snapshot of the repo.  
Under that ref, use **flat** per-GPU directories (no `1.0.0/` semver subdirs):

```text
variants/
├── sm89-cu124-linux-x86_64/
│   ├── flashcli-bundle.json
│   ├── partner/              # optional; usually packed into runtime/python/partner/
│   └── runtime/
└── sm120-cu128-linux-x86_64/
    ├── flashcli-bundle.json
    └── runtime/
```

Freeze a release:

```bash
git tag bundle-1.1.0
# models.yaml: bundle.git.ref: bundle-1.1.0
```

CLI: `flashcli run my-model --bundle-ref bundle-1.1.0`
