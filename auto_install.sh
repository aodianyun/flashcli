#!/bin/sh
# auto_install.sh — pick GitHub or Gitee install.sh based on flags / reachability.
#
# Usage:
#   curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh -s -- [OPTIONS]
#   curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/auto_install.sh | sh -s -- [OPTIONS]
#
# All arguments are forwarded to install.sh.
#   --mirror / --gitee  → download install.sh from Gitee (and ensure --mirror for install)
#   --github            → download install.sh from GitHub
#   (default)           → probe GitHub; on failure/timeout fall back to Gitee + --mirror
#
# install.sh is saved to $FLASHCLI_HOME/install.sh (default ~/.flashcli) then executed,
# so re-runs can use: ~/.flashcli/install.sh --mirror
#
# Downloads use connect/max timeouts so a half-open GitHub link cannot hang forever.

set -eu

GITHUB_INSTALL="https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh"
GITEE_INSTALL="https://gitee.com/aodiansoft/flashcli/raw/main/install.sh"
PROBE_TIMEOUT="${FLASHCLI_PROBE_TIMEOUT:-8}"
DOWNLOAD_TIMEOUT="${FLASHCLI_DOWNLOAD_TIMEOUT:-60}"

info() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }

flashcli_home_path() {
  printf '%s' "${FLASHCLI_HOME:-${HOME:-/root}/.flashcli}"
}

has_flag() {
  _needle="$1"
  shift
  for arg in "$@"; do
    case "$arg" in
      "$_needle") return 0 ;;
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

download_install_sh() {
  _url="$1"
  _dest="$2"
  _tmp="${_dest}.tmp.$$"
  mkdir -p "$(dirname "$_dest")"
  info "[i] saving install.sh → ${_dest}"
  info "[i] fetching: ${_url}"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --connect-timeout "$PROBE_TIMEOUT" --max-time "$DOWNLOAD_TIMEOUT" \
      -o "$_tmp" "$_url"
  elif command -v wget >/dev/null 2>&1; then
    wget -q --timeout="$DOWNLOAD_TIMEOUT" -O "$_tmp" "$_url"
  else
    printf 'error: curl or wget required\n' >&2
    return 1
  fi
  mv -f "$_tmp" "$_dest"
  chmod +x "$_dest"
}

run_saved_install_sh() {
  _dest="$1"
  shift
  info "[i] running: ${_dest} $*"
  sh "$_dest" "$@"
}

# Prefer Gitee when user asked for China mirrors / Gitee; --github forces GitHub.
if has_flag --github "$@"; then
  info "[i] --github: using GitHub install.sh"
  INSTALL_URL="$GITHUB_INSTALL"
elif has_flag --mirror "$@" || has_flag --gitee "$@"; then
  info "[i] --mirror/--gitee: using Gitee install.sh"
  INSTALL_URL="$GITEE_INSTALL"
  if ! has_flag --mirror "$@"; then
    set -- --mirror "$@"
  fi
elif github_reachable; then
  info "[i] network: GitHub reachable — using GitHub install.sh"
  INSTALL_URL="$GITHUB_INSTALL"
else
  info "[i] network: GitHub unreachable — using Gitee install.sh (--mirror)"
  INSTALL_URL="$GITEE_INSTALL"
  if ! has_flag --mirror "$@"; then
    set -- --mirror "$@"
  fi
fi

INSTALL_DEST="$(flashcli_home_path)/install.sh"

if download_install_sh "$INSTALL_URL" "$INSTALL_DEST"; then
  :
else
  _ec=$?
  rm -f "${INSTALL_DEST}.tmp.$$" 2>/dev/null || true
  if [ "$INSTALL_URL" = "$GITHUB_INSTALL" ]; then
    warn "[!] GitHub install.sh failed or timed out (exit ${_ec}) — retrying via Gitee"
    INSTALL_URL="$GITEE_INSTALL"
    if ! has_flag --mirror "$@"; then
      set -- --mirror "$@"
    fi
    download_install_sh "$INSTALL_URL" "$INSTALL_DEST" || exit $?
  else
    exit "$_ec"
  fi
fi

run_saved_install_sh "$INSTALL_DEST" "$@"
exit $?
