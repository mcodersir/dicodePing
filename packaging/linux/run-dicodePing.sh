#!/usr/bin/env bash
# dicodePing RC19 Linux launcher.
# Launch normally. The application requests the TUN privilege through PolicyKit
# and preserves the current user's HOME, display and desktop-session variables.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN="$HERE/dicodePing"
if [ ! -x "$BIN" ] && [ -f "$BIN" ]; then
    chmod +x "$BIN" 2>/dev/null || true
fi
if [ ! -x "$BIN" ]; then
    echo "Error: dicodePing executable not found: $BIN" >&2
    exit 1
fi
exec "$BIN" "$@"
