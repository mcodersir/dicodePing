dicodePing v2.0.0-rc.1 for Linux x86_64

روش اجرا / How to run
======================

در پوشه استخراج‌شده اجرا کنید:

    ./run-dicodePing.sh

برنامه را عادی اجرا کنید. هنگام شروع اتصال Xray، پنجره PolicyKit برای
دسترسی لازم TUN نمایش داده می‌شود. برنامه سپس با حفظ HOME، DISPLAY،
Wayland/X11 و نشست کاربر دوباره اجرا می‌شود.

Run the launcher normally. When an Xray connection starts, PolicyKit asks
for the privileges required to create and route a TUN interface. The app
preserves the user's HOME, display and desktop-session environment.

اتصال Xray / Xray connection
----------------------------
مسیر اتصال 2.0 RC1 یک VPN کامل مبتنی بر TUN است:

    System traffic -> Xray TUN -> selected Xray server -> Internet

System Proxy جایگزین TUN نیست. قبل از نمایش وضعیت Connected، برنامه هم
خود سرور و هم عبور یک درخواست مستقیم بدون Proxy از Route سراسری TUN را
بررسی می‌کند.

2.0 RC1 uses full-device TUN routing, not desktop proxy settings. Before it
reports Connected, it verifies both the chosen server and an ordinary
no-proxy HTTP request through the system TUN route.

نیازمندی‌های سیستم / System requirements
-----------------------------------------
- توزیع ۶۴ بیتی مدرن GNU/Linux با glibc
- PolicyKit و ابزار `pkexec`
- پشتیبانی kernel از TUN (`/dev/net/tun`)
- ابزار `ip` از بسته iproute2

- Modern 64-bit GNU/Linux distribution with glibc
- PolicyKit and `pkexec`
- Kernel TUN support (`/dev/net/tun`)
- `ip` from iproute2

کتابخانه‌های رابط روی Debian/Ubuntu:

    sudo apt-get install -y --no-install-recommends \
      policykit-1 iproute2 libegl1 libgl1 libxcb-cursor0 libxcb-icccm4 \
      libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-util1 \
      libxcb-xkb1 libxkbcommon-x11-0

عیب‌یابی / Troubleshooting
--------------------------
- وجود TUN را بررسی کنید: `test -c /dev/net/tun && echo OK`
- وجود PolicyKit را بررسی کنید: `command -v pkexec`
- اگر پنجره مجوز را لغو کنید، اتصال TUN آغاز نمی‌شود.
- برای دیدن خطای اولیه، `./dicodePing` را از ترمینال اجرا کنید.
