#!/bin/sh
# Printed on login (motd) and via: flashcli-bundle-build-help
cat <<'EOF'
========================================
 flashcli-bundle-build
 Ubuntu 22.04 + CUDA 13 + g++-11 + OpenCode
========================================

Compile floor: CC/CXX/CUDAHOSTCXX = gcc/g++-11

China network defaults:
  apt  → mirrors.aliyun.com
  pip  → pypi.tuna.tsinghua.edu.cn
  npm  → registry.npmmirror.com
  HF   → hf-mirror.com
  FLASHCLI_USE_MIRROR=1
  re-apply: apply-cn-mirrors

OpenCode (one-click background):
  opencode-bg              # start + auto-restart on :8080
  opencode-bg status
  opencode-bg logs -f
  opencode-bg stop
  opencode-web             # foreground

Host browser: map -p 8080:8080 then open http://<host>:8080
  Settings → Providers → More → search "zhipu"
  → Zhipu AI Coding Plan → paste API key

Re-show this tip: flashcli-bundle-build-help
========================================
EOF
