#!/bin/sh
# auto_install.sh — pick GitHub or Gitee install.sh based on network reachability.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/auto_install.sh | sh -s -- [OPTIONS]
#   curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/auto_install.sh | sh -s -- [OPTIONS]
#
# All arguments are forwarded to install.sh. On restricted network (Gitee fallback),
# --mirror is added by default unless already present.

set -eu

GITHUB_INSTALL="https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh"
GITEE_INSTALL="https://gitee.com/aodiansoft/flashcli/raw/main/install.sh"
PROBE_TIMEOUT="${FLASHCLI_PROBE_TIMEOUT:-8}"

info() { printf '%s\n' "$*"; }

has_mirror_flag() {
  for arg in "$@"; do
    case "$arg" in
      --mirror) return 0 ;;
    esac
  done
  return 1
}

github_reachable() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --connect-timeout "$PROBE_TIMEOUT" --max-time "$PROBE_TIMEOUT" \
      -o /dev/null "$GITHUB_INSTALL" 2>/dev/null
    return $?
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -q --timeout="$PROBE_TIMEOUT" -O /dev/null "$GITHUB_INSTALL" 2>/dev/null
    return $?
  fi
  return 1
}

if github_reachable; then
  info "[i] network: GitHub reachable — using GitHub install.sh"
  INSTALL_URL="$GITHUB_INSTALL"
else
  info "[i] network: GitHub unreachable — using Gitee install.sh (--mirror)"
  INSTALL_URL="$GITEE_INSTALL"
  if ! has_mirror_flag "$@"; then
    set -- --mirror "$@"
  fi
fi

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$INSTALL_URL" | sh -s -- "$@"
  exit $?
fi

if command -v wget >/dev/null 2>&1; then
  wget -qO- "$INSTALL_URL" | sh -s -- "$@"
  exit $?
fi

printf 'error: curl or wget required\n' >&2
exit 1
