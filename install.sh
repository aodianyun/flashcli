#!/bin/sh
# flashcli installer — Go host only.
#
# Fetches and runs scripts/install_go.sh, which downloads the static
# flashcli-<os>-<arch> binary + sha256sums.txt and verifies sha256.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
#   curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
#
# Options (forwarded to install_go.sh):
#   --mirror, --gitee   Use Gitee release assets
#   --github            Use GitHub release assets (default)
#   --version V         Install a specific version (default: latest release)
#   --dir DIR           Install directory
#   -h, --help          Show install_go.sh help
#
# Env:
#   FLASHCLI_INSTALL_REF       ref used to fetch scripts/install_go.sh (default: main)
#   FLASHCLI_GO_SCRIPT_URL     override the install_go.sh URL (e.g. file://…)
#   FLASHCLI_GO_VERSION        release version (forwarded)
#   FLASHCLI_GO_INSTALL_DIR    install directory (forwarded)
set -eu

REF="${FLASHCLI_INSTALL_REF:-main}"

mirror=0
for a in "$@"; do
  case "$a" in
    --mirror|--gitee) mirror=1 ;;
    --github) mirror=0 ;;
    -h|--help) : ;;
  esac
done
case "${FLASHCLI_USE_MIRROR:-0}" in 1|true|yes|on) mirror=1 ;; esac

case "${FLASHCLI_GO_SCRIPT_URL:-}" in
  "")
    if [ "$mirror" = 1 ]; then
      url="https://gitee.com/aodiansoft/flashcli/raw/${REF}/scripts/install_go.sh"
    else
      url="https://raw.githubusercontent.com/aodianyun/flashcli/${REF}/scripts/install_go.sh"
    fi
    ;;
  *) url="$FLASHCLI_GO_SCRIPT_URL" ;;
esac

tmp="$(mktemp 2>/dev/null || echo "/tmp/flashcli-install-go.$$")"
trap 'rm -f "$tmp" 2>/dev/null || true' EXIT

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$url" -o "$tmp"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$tmp" "$url"
else
  echo "error: curl or wget required" >&2
  exit 1
fi

FLASHCLI_INSTALL_REF="$REF" sh "$tmp" "$@"
