dicodePing v0.1.5-rc.3 for Linux x86_64

1. Extract the archive.
2. Run: ./run-dicodePing.sh

The launcher requests administrator permission because creating and routing a
TUN interface requires root/CAP_NET_ADMIN. PolicyKit is preferred; sudo is the
fallback. The application, UI, server selection and Xray connection logic are
shared with the Windows build.

Supported target: modern 64-bit Linux distributions with glibc and a desktop
session (X11 or Wayland/XWayland).

Required desktop libraries on Debian/Ubuntu:
  libegl1 libgl1 libxcb-cursor0 libxcb-icccm4 libxcb-image0
  libxcb-keysyms1 libxcb-render-util0 libxcb-util1 libxcb-xkb1
  libxkbcommon-x11-0
