#!/usr/bin/env bash
# dicodePing Linux launcher.
#
# Usage:
#   ./run-dicodePing.sh                  # default — prompt for admin password
#   ./run-dicodePing.sh --no-admin       # try without root (TUN connection will fail)
#   SUDO_ASKPASS=/usr/bin/ssh-askpass ./run-dicodePing.sh
#
# A TUN interface needs CAP_NET_ADMIN.  We try, in order:
#   1. pkexec (Polkit graphical prompt, best on GNOME/KDE)
#   2. sudo -A (uses SUDO_ASKPASS or falls back to terminal prompt)
#   3. sudo -E (terminal password prompt)
#   4. gksudo / kdesudo (older desktops)
# If everything fails we print a friendly Persian/English error.

set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN="$HERE/dicodePing"

if [ ! -x "$BIN" ]; then
    if [ -f "$BIN" ]; then
        chmod +x "$BIN" 2>/dev/null || true
    fi
fi

if [ ! -x "$BIN" ]; then
    echo "خطا: فایل اجرایی dicodePing در مسیر زیر یافت نشد:" >&2
    echo "  $BIN" >&2
    echo "Error: dicodePing executable not found at: $BIN" >&2
    exit 1
fi

# Skip privilege escalation if requested (e.g. for tests or first-run UI).
if [ "${1:-}" = "--no-admin" ]; then
    shift
    exec "$BIN" "$@"
fi

# Already root?  Run directly.
if [ "$(id -u)" -eq 0 ]; then
    exec "$BIN" "$@"
fi

# Pass through the display so the GUI shows up under pkexec/sudo.
PASSTHRU_ENV=(
    "DISPLAY=${DISPLAY:-}"
    "XAUTHORITY=${XAUTHORITY:-}"
    "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}"
    "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-}"
    "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-}"
    "DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-}"
    "LANG=${LANG:-C.UTF-8}"
    "LC_ALL=${LC_ALL:-${LANG:-C.UTF-8}}"
)

run_with_env() {
    local launcher="$1"; shift
    env "${PASSTHRU_ENV[@]}" "$launcher" "$BIN" "$@"
}

# 1) pkexec (preferred — graphical polkit prompt)
if command -v pkexec >/dev/null 2>&1; then
    if run_with_env pkexec "$@"; then
        exit 0
    fi
    echo "تنظیم: pkexec ناموفق بود، روش بعدی امتحان می‌شود..." >&2
    echo "Note: pkexec failed, trying next method..." >&2
fi

# 2) gksudo / kdesudo (older desktops without polkit)
for graphical_sudo in gksudo kdesudo; do
    if command -v "$graphical_sudo" >/dev/null 2>&1; then
        if run_with_env "$graphical_sudo" "$@"; then
            exit 0
        fi
    fi
done

# 3) sudo with askpass if available (graphical password prompt via SUDO_ASKPASS)
if [ -n "${SUDO_ASKPASS:-}" ] && command -v sudo >/dev/null 2>&1; then
    if env "${PASSTHRU_ENV[@]}" sudo -A -E "$BIN" "$@"; then
        exit 0
    fi
fi

# 4) sudo -E (terminal password prompt)
if command -v sudo >/dev/null 2>&1; then
    if env "${PASSTHRU_ENV[@]}" sudo -E "$BIN" "$@"; then
        exit 0
    fi
fi

# Everything failed.  Print a friendly explanation.
cat >&2 <<'EOF'

========================================
dicodePing راه‌اندازی نشد
========================================

برای اجرای dicodePing روی لینوکس به یکی از موارد زیر نیاز است:

  ۱. pkexec (Polkit) — روی اکثر توزیع‌های مدرن نصب است.
  ۲. sudo — برای وارد کردن رمز در ترمینال.

یا این دستور را مستقیم اجرا کنید:

    sudo ./dicodePing

----------------------------------------

dicodePing could not be launched.

On Linux, dicodePing needs one of these to obtain TUN privileges:

  1. pkexec (Polkit) — installed on most modern distributions.
  2. sudo — to enter your password in a terminal.

Or run the binary directly:

    sudo ./dicodePing

EOF

exit 1
