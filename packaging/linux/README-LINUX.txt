dicodePing v1.6.0-rc.1 for Linux x86_64

روش اجرا / How to run
======================

ساده‌ترین راه / Easiest way
----------------------------
در پوشه استخراج‌شده روی فایل `run-dicodePing.sh` دوبار کلیک کنید،
یا در ترمینال بنویسید:

    ./run-dicodePing.sh

برنامه از شما رمز مدیر (root) را می‌خواهد، چون ساخت رابط TUN
به دسترسی مدیر نیاز دارد. اگر `pkexec` نصب باشد، یک پنجره گرافیکی
نمایش داده می‌شود؛ در غیر این صورت از `sudo` در ترمینال استفاده
می‌شود.

Double-click `run-dicodePing.sh` in the extracted folder, or run:

    ./run-dicodePing.sh

The launcher requests administrator permission because creating and
routing a TUN interface requires root/CAP_NET_ADMIN.  PolicyKit is
preferred; sudo is the fallback.

اجرای مستقیم / Direct run
--------------------------
    sudo ./dicodePing

نصب در منوی برنامه‌ها / Install application menu entry
-------------------------------------------------------
فایل `dicodePing.desktop` را در مسیر زیر کپی کنید:

    mkdir -p ~/.local/share/applications
    cp dicodePing.desktop ~/.local/share/applications/
    # Edit the Exec/Icon paths to point to this folder.

روی اکثر توزیع‌ها بعد از کپی، dicodePing در منوی برنامه‌ها ظاهر
می‌شود و با کلیک اجرا می‌گردد.

On most distributions, copying `dicodePing.desktop` to
`~/.local/share/applications/` (and editing the Exec/Icon paths)
makes dicodePing appear in the application menu.

نیازمندی‌های سیستم / System requirements
-----------------------------------------
- توزیع ۶۴ بیتی مدرن گنو/لینوکس با glibc و جلسه دسکتاپ (X11 یا Wayland/XWayland)
- Modern 64-bit Linux distribution with glibc and a desktop session
  (X11 or Wayland/XWayland).

کتابخانه‌های دسکتاپ مورد نیاز روی Debian/Ubuntu:
  libegl1 libgl1 libxcb-cursor0 libxcb-icccm4 libxcb-image0
  libxcb-keysyms1 libxcb-render-util0 libxcb-util1 libxcb-xkb1
  libxkbcommon-x11-0

نصب با apt:
  sudo apt-get install -y --no-install-recommends \
    libegl1 libgl1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-render-util0 libxcb-util1 libxcb-xkb1 \
    libxkbcommon-x11-0 policykit-1

فونت‌ها / Fonts
---------------
فونت Vazirmatn به‌صورت داخلی در بسته قرار داده شده است، پس نیازی
به نصب جداگانه فونت فارسی نیست.  Vazirmatn is bundled inside the
archive; no separate Persian font installation is required.

عیب‌یابی / Troubleshooting
--------------------------
- اگر برنامه اجرا نشد، در ترمینال اجرا کنید تا خطا نمایش داده شود:
  `./dicodePing`
- اگر پنجره گرافیکی برای رمز مدیر ظاهر نشد، `policykit-1` را نصب کنید.
- If the GUI does not launch, run from terminal to see the error.
- If no graphical password prompt appears, install `policykit-1`.
