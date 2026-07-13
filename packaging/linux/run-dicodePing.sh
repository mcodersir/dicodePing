#!/usr/bin/env sh
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "$(id -u)" -eq 0 ]; then
  exec "$HERE/dicodePing" "$@"
fi

if command -v pkexec >/dev/null 2>&1; then
  exec pkexec env \
    DISPLAY="${DISPLAY:-}" \
    XAUTHORITY="${XAUTHORITY:-}" \
    WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" \
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" \
    "$HERE/dicodePing" "$@"
fi

exec sudo -E "$HERE/dicodePing" "$@"
