#!/bin/bash
# Configure China-friendly defaults for flashcli-bundle-build (apt / pip / npm / HF).
# Idempotent; safe to re-run inside a container.
set -eu

APT_MIRROR="${FLASHCLI_APT_MIRROR:-https://mirrors.aliyun.com}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.tuna.tsinghua.edu.cn}"
NPM_REGISTRY="${NPM_CONFIG_REGISTRY:-${NPM_REGISTRY:-https://registry.npmmirror.com}}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

rewrite_apt_file() {
  local f="$1"
  [[ -f "${f}" ]] || return 0
  sed -i \
    -e "s|https\\?://archive\\.ubuntu\\.com/ubuntu/|${APT_MIRROR}/ubuntu/|g" \
    -e "s|https\\?://security\\.ubuntu\\.com/ubuntu/|${APT_MIRROR}/ubuntu/|g" \
    -e "s|https\\?://ports\\.ubuntu\\.com/ubuntu-ports/|${APT_MIRROR}/ubuntu-ports/|g" \
    -e "s|https\\?://archive\\.ubuntu\\.com/ubuntu|${APT_MIRROR}/ubuntu|g" \
    -e "s|https\\?://security\\.ubuntu\\.com/ubuntu|${APT_MIRROR}/ubuntu|g" \
    -e "s|https\\?://cn\\.archive\\.ubuntu\\.com/ubuntu/|${APT_MIRROR}/ubuntu/|g" \
    -e "s|https\\?://cn\\.archive\\.ubuntu\\.com/ubuntu|${APT_MIRROR}/ubuntu|g" \
    -e "s|https\\?://mirrors\\.cloud\\.tencent\\.com/ubuntu/|${APT_MIRROR}/ubuntu/|g" \
    -e "s|https\\?://mirrors\\.tuna\\.tsinghua\\.edu\\.cn/ubuntu/|${APT_MIRROR}/ubuntu/|g" \
    -e "s|https\\?://deb\\.debian\\.org/debian/|${APT_MIRROR}/debian/|g" \
    -e "s|https\\?://security\\.debian\\.org/debian-security/|${APT_MIRROR}/debian-security/|g" \
    -e "s|https\\?://deb\\.debian\\.org/debian|${APT_MIRROR}/debian|g" \
    -e "s|https\\?://security\\.debian\\.org/debian-security|${APT_MIRROR}/debian-security|g" \
    "${f}" 2>/dev/null || true
}

apply_apt() {
  command -v sed >/dev/null 2>&1 || return 0
  [[ -d /etc/apt ]] || return 0
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    rewrite_apt_file "${f}"
  done
  echo "[cn-mirrors] apt → ${APT_MIRROR} (ubuntu/debian URLs only; NVIDIA CUDA repos unchanged)"
}

apply_pip() {
  mkdir -p /etc/pip /root/.config/pip /root/.pip
  local host
  host="$(printf '%s' "${PIP_TRUSTED_HOST}" | sed 's|/*$||')"
  cat >/etc/pip.conf <<EOF
[global]
index-url = ${PIP_INDEX_URL}
trusted-host = ${host}
timeout = 120
EOF
  cp -f /etc/pip.conf /root/.config/pip/pip.conf
  cp -f /etc/pip.conf /root/.pip/pip.conf
  cat >/etc/profile.d/flashcli-cn-mirrors.sh <<EOF
# flashcli-bundle-build China network defaults
export PIP_INDEX_URL="${PIP_INDEX_URL}"
export PIP_TRUSTED_HOST="${host}"
export UV_DEFAULT_INDEX="${PIP_INDEX_URL}"
export UV_INDEX_URL="${PIP_INDEX_URL}"
export HF_ENDPOINT="${HF_ENDPOINT}"
export HF_HUB_DISABLE_XET="\${HF_HUB_DISABLE_XET:-1}"
export NPM_CONFIG_REGISTRY="${NPM_REGISTRY}"
export FLASHCLI_USE_MIRROR="\${FLASHCLI_USE_MIRROR:-1}"
EOF
  chmod 644 /etc/profile.d/flashcli-cn-mirrors.sh
  echo "[cn-mirrors] pip → ${PIP_INDEX_URL}"
}

apply_npm() {
  mkdir -p /root
  npm config set registry "${NPM_REGISTRY}" >/dev/null 2>&1 || true
  cat >/root/.npmrc <<EOF
registry=${NPM_REGISTRY}
fetch-timeout=120000
EOF
  mkdir -p /etc
  cat >/etc/npmrc <<EOF
registry=${NPM_REGISTRY}
fetch-timeout=120000
EOF
  echo "[cn-mirrors] npm → ${NPM_REGISTRY}"
}

apply_hf_note() {
  echo "[cn-mirrors] HF_ENDPOINT → ${HF_ENDPOINT}"
}

main() {
  apply_apt
  apply_pip
  apply_npm
  apply_hf_note
  echo "[cn-mirrors] done"
}

main "$@"
