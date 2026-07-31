# dicodePing

> کلاینت چندسکویی فارسی/انگلیسی برای دریافت، ارزیابی و اتصال به کانفیگ‌های پروکسی با Xray TUN واقعی — برای Windows، Linux، macOS و Android.

[![Latest Release](https://img.shields.io/github/v/release/mcodersir/dicodePing?style=flat-square&label=%D9%86%D8%B3%D8%AE%D9%87%20%D9%BE%D8%A7%DB%8C%D8%AF%D8%A7%D8%B1)](https://github.com/mcodersir/dicodePing/releases/latest)
[![Platforms](https://img.shields.io/badge/%D9%BE%D9%84%D8%AA%D9%81%D8%B1%D9%85-4-blue?style=flat-square)](#%D8%AF%D8%A7%D9%86%D9%84%D9%88%D8%AF)
[![License](https://img.shields.io/badge/%D9%85%D8%AC%D9%88%D8%B2-GPL--3.0-blue?style=flat-square)](LICENSE)

dicodePing یک کلاینت مستقل و قابل اعتماد برای دسترسی به اینترنت آزاد است که کانفیگ‌های پروکسی را از کانال‌های تلگرام دریافت، با پروب‌های واقعی TCP و Xray HTTP ارزیابی، و از طریق TUN سراسری به‌صورت شفاف روی کل دستگاه اعمال می‌کند. نسخه دسکتاپ با PySide6 و نسخه اندروید با Kotlin و AndroidX ساخته شده‌اند؛ هر دو از یک کد مشترک برای طبقه‌بندی کانفیگ، ارزیابی امنیتی و گزارش کیفیت اتصال استفاده می‌کنند.

## فهرست

- [ویژگی‌ها](#ویژگی‌ها)
- [دانلود](#دانلود)
- [نصب](#نصب)
  - [Windows](#windows)
  - [Linux](#linux)
  - [macOS](#macos)
  - [Android](#android)
- [معماری](#معماری)
- [اسکنر](#اسکنر)
  - [جریان سه‌مرحله‌ای](#جریان-سه%D9%85%D8%B1%D8%AD%D9%84%D9%87%E2%80%8C%D8%A7%DB%8C)
  - [همزمانی واقعی (v2.0.5)](#%D9%87%D9%85%D8%B2%D9%85%D8%A7%D9%86%DB%8C-%D9%88%D8%A7%D9%82%D8%B9%DB%8C-v202)
  - [ذخیره فوری + مودال محاسبه پینگ/لوکیشن](#%D8%B0%D8%AE%DB%8C%D8%B1%D9%87-%D9%81%D9%88%D8%B1%DB%8C--%D9%85%D9%88%D8%AF%D8%A7%D9%84-%D9%85%D8%AD%D8%A7%D8%B3%D8%A8%D9%87-%D9%BE%DB%8C%D9%86%DA%AF%D9%84%D9%88%DA%A9%DB%8C%D8%B4%D9%86)
- [هسته‌ها](#%D9%87%D8%B3%D8%AA%D9%87%E2%80%8C%D9%87%D8%A7)
- [امنیت](#%D8%A7%D9%85%D9%86%DB%8C%D8%AA)
- [زبان‌ها و RTL](#%D8%B2%D8%A8%D8%A7%D9%86%E2%80%8C%D9%87%D8%A7-%D9%88-rtl)
- [ساخت از سورس](#%D8%B3%D8%A7%D8%AE%D8%AA-%D8%A7%D8%B2-%D8%B3%D9%88%D8%B1%D8%B3)
  - [پیش‌نیازها](#%D9%BE%DB%8C%D8%B4%E2%80%8C%D9%86%DB%8C%D8%A7%D8%B2%D9%87%D8%A7)
  - [ساخت دسکتاپ](#%D8%B3%D8%A7%D8%AE%D8%AA-%D8%AF%D8%B3%DA%A9%D8%AA%D8%A7%D9%BE)
  - [ساخت Android](#%D8%B3%D8%A7%D8%AE%D8%AA-android)
- [اعتبارسنجی و تست](#%D8%A7%D8%B9%D8%AA%D8%A8%D8%A7%D8%B1%D8%B3%D9%86%D8%AC%DB%8C-%D9%88-%D8%AA%D8%B3%D8%AA)
- [انتشار یک‌کلیکی](#%D8%A7%D9%86%D8%AA%D8%B4%D8%A7%D8%B1-%DB%8C%DA%A9%E2%80%8C%DA%A9%D9%84%DB%8C%DA%A9%DB%8C)
- [عیب‌یابی](#%D8%B9%DB%8C%D8%A8%E2%80%8C%DB%8C%D8%A7%D8%A8%DB%8C)
- [حریم خصوصی](#%D8%AD%D8%B1%DB%8C%D9%85-%D8%AE%D8%B5%D9%88%D8%B5%DB%8C%D8%AA)
- [مشارکت](#%D9%85%D8%B4%D8%A7%D8%B1%DA%A9%D8%AA)
- [مجوز](#%D9%85%D8%AC%D9%88%D8%B2)
- [سپاسگزاری‌ها](#%D8%B3%D9%BE%D8%A7%D8%B3%DA%AF%D8%B2%D8%A7%D8%B1%DB%8C%E2%80%8C%D9%87%D8%A7)

## ویژگی‌ها

- **تستر کانفیگ واقعی** — هر کانفیگ با یک پروب TCP و یک درخواست HTTP واقعی از داخل Xray سنجیده می‌شود. پینگ نمایش‌داده‌شده همان تاخیر واقعی یک صفحه `204` از طریق پروکسی است، نه ICMP یا TCP خام.
- **اسکنر خودکار** — با یک کلیک، کانال‌های تلگرام منتخب را می‌کشد، کانفیگ‌های یکتا را استخراج می‌کند، VPN بوت‌استرپ را قطع می‌کند و هر کانفیگ را به‌صورت همزمان تست می‌کند. سرورهای سالم در یک SUB به‌صورت اتمیک ذخیره می‌شوند.
- **اتصال TUN سراسری** — روی دسکتاپ با Wintun (Windows) و TUN/Userspace (Linux/macOS)، روی اندروید با VpnService. کل ترافیک دستگاه از داخل تونل می‌گذرد.
- **سه هسته مستقل** — Xray برای اتصال پیش‌فرض، Aether برای اتصال جایگزین و SOCKS داخلی، WARP/Usque برای Cloudflare WARP. هر هسته با امضای SHA-256 رسمی اعتبارسنجی می‌شود.
- **فونت فارسی قطعی** — Vazirmatn Regular/Medium/Bold نسخه 33.0.3 در زمان Build از بسته رسمی npm دریافت، با SHA-512 کنترل و داخل بسته نهایی ثبت می‌شود. هیچ وابستگی به فونت سیستم یا Google Fonts وجود ندارد.
- **ارزیابی امنیتی هر کانفیگ** — هر کانفیگ بر اساس پروتکل، رمزنگاری، transport و آدرس سرور امتیازبندی می‌شود (امن / هشدار / خطرناک).
- **طبقه‌بندی خودکار پروفایل** — کانفیگ‌ها به‌صورت `auto`، `manual`، `persistent` و `cdn` طبقه‌بندی می‌شوند.
- **کشف ژئو** — IP هر سرور با یک resolver محلی حل می‌شود و کشور، منطقه، شهر، ISP و ASN از طریق یک سرویس ژئو با کش محلی و فورس‌ریفرش اختیاری استخراج می‌شود.
- **پشتیبانی کامل از RTL** — رابط فارسی و انگلیسی با چیدمان راست‌به‌چپ واقعی.
- **بدون Google Play** — APK با امضای رسمی مستقل از GitHub منتشر می‌شود.
- **بدون تلمتر** — هیچ داده‌ای به هیچ سروری ارسال نمی‌شود؛ تمام تنظیمات و تاریخچه به‌صورت محلی ذخیره می‌شوند.

## دانلود

آخرین نسخه پایدار را از [صفحه انتشارها](https://github.com/mcodersir/dicodePing/releases/latest) دانلود کنید.

| پلتفرم | فایل | حداقل نسخه |
|---|---|---|
| Windows (64-bit) | `dicodePing-v*.*.*-windows-x64.exe` | Windows 10 1809 |
| Linux (64-bit) | `dicodePing-v*.*.*-linux-x86_64.tar.gz` | Ubuntu 20.04 / glibc 2.31 |
| macOS (Apple Silicon) | `dicodePing-v*.*.*-macos-arm64.dmg` | macOS 11 Big Sur |
| macOS (Intel) | `dicodePing-v*.*.*-macos-x86_64.dmg` | macOS 11 Big Sur |
| Android | `dicodePing-v*.*.*-android.apk` | Android 7.0 (API 24) |

برای صحت فایل دانلودشده، SHA-256 آن را با فایل `SHA256SUMS` همراه هر انتشار مقایسه کنید.

## نصب

### Windows

1. فایل `dicodePing-v*.*.*-windows-x64.exe` را دانلود کنید.
2. روی آن دابل‌کلیک کنید. اگر SmartScreen هشدار داد، روی **More info → Run anyway** کلیک کنید (فایل با یک گواهی خودامضاشده محلی امضا شده است).
3. Xray، Wintun و Vazirmatn داخل خود فایل بسته‌بندی شده‌اند — نیازی به نصب جداگانه ندارید.

### Linux

1. فایل `dicodePing-v*.*.*-linux-x86_64.tar.gz` را دانلود کنید.
2. آن را استخراج کنید:
   ```bash
   tar -xzf dicodePing-v*.*.*-linux-x86_64.tar.gz
   cd dicodePing-v*.*.*-linux-x86_64
   ```
3. اجرا کنید:
   ```bash
   ./dicodePing
   ```
4. برای ادغام با دسکتاپ، فایل `packaging/linux/dicodePing.desktop` را در `~/.local/share/applications/` کپی کنید.

### macOS

1. فایل DMG متناسب با پردازنده‌تان را دانلود کنید (Apple Silicon برای M1/M2/M3، Intel برای پردازنده‌های قدیمی‌تر).
2. فایل DMG را باز کنید و `dicodePing.app` را در پوشه `Applications` بکشید.
3. اولین بار با کلیک راست → **Open** اجرا کنید تا Gatekeeper آن را تأیید کند.
4. اگر خطای "cannot be opened because the developer cannot be verified" دیدید، در Terminal اجرا کنید:
   ```bash
   xattr -dr com.apple.quarantine /Applications/dicodePing.app
   ```

### Android

1. فایل `dicodePing-v*.*.*-android.apk` را دانلود کنید.
2. در تنظیمات اندروید، **Settings → Security → Install unknown apps** (یا **Settings → Apps → Special access → Install unknown apps**) را برای مرورگرتان فعال کنید.
3. روی فایل APK ضربه بزنید و **Install** را بزنید.
4. بعد از نصب، **Settings → Apps → dicodePing → Permissions** را باز کنید و مجوز VPN را در صورت درخواست تأیید کنید.
5. APK شامل `arm64-v8a` و `x86_64` است — هم روی گوشی‌های واقعی و هم روی شبیه‌سازها کار می‌کند.

## معماری

```
┌─────────────────────────────────────────────────────────────┐
│                        رابط کاربری                          │
│  PySide6 (Desktop)            │  Kotlin + AndroidX (Android)│
├─────────────────────────────────────────────────────────────┤
│                    لایه منطق مشترک                          │
│  config_checker  config_profile  config_security_rating     │
│  connection_quality  discovery  crawler  scanner            │
│  geo  icmp_ping  ping_cache  protocols  storage  updates    │
├─────────────────────────────────────────────────────────────┤
│                       لایه هسته                              │
│  Xray (TUN)   │   Aether (SOCKS)   │   WARP/Usque (WireGuard)│
├─────────────────────────────────────────────────────────────┤
│                     لایه ترافیک                             │
│  Wintun (Win)  │  TUN/Userspace (Lin/Mac)  │  VpnService (Android) │
└─────────────────────────────────────────────────────────────┘
```

کد مشترک بین دسکتاپ و اندروید در پوشه `shared/` و `dicodeping/` قرار دارد؛ کد اختصاصی دسکتاپ در `app.py` و `app_v200.py`، و کد اختصاصی اندروید در `dicodePing_android/app/src/main/java/ir/dicode/ping/` است.

## اسکنر

اسکنر قلب dicodePing است. این فرآیند سه‌مرحله‌ای، کانال‌های تلگرام را می‌کشد، کانفیگ‌ها را ارزیابی و سرورهای سالم را در یک SUB ذخیره می‌کند.

### جریان سه‌مرحله‌ای

**مرحله ۱ — اتصال:** بهترین سرور بوت‌استرپ از منابع موجود انتخاب و یک TUN واقعی برقرار می‌شود. اتصال فقط پس از موفقیت یک درخواست HTTP تأیید می‌شود.

**مرحله ۲ — دریافت + قطع + تست:**
- کانال‌های تلگرام به‌صورت همزمان با `TelegramChannelCrawler` کشیده می‌شوند (تا ۱۸ کانال موازی روی دسکتاپ، ۳-۸ روی اندروید).
- کانفیگ‌های یکتا استخراج و در یک فایل موقت ذخیره می‌شوند.
- VPN بوت‌استرپ قطع می‌شود تا تست‌ها از طریق بوت‌استرپ انجام نشوند (این حیاتی است — در غیر این صورت تست، عملکرد سرور بوت‌استرپ را می‌سنجد نه کانفیگ‌های کشیده‌شده را).
- هر کانفیگ با پروب‌های واقعی تست می‌شود.

**مرحله ۳ — ذخیره:** سرورهای سالم به‌صورت اتمیک در یک SUB جدید به نام `SUB` ذخیره می‌شوند. سابقه‌ی اسکن در `scanner-history.json` نگه‌داری می‌شود.

### همزمانی واقعی (v2.0.5)

در نسخه‌های قبلی، پروب‌های Xray HTTP روی اندروید به‌دلیل قفل process-wide کتابخانه `libv2ray` به‌صورت ترتیبی اجرا می‌شدند، حتی وقتی تعداد workerها افزایش می‌یافت. v2.0.2 این مشکل را با یک معماری دو‌فازی حل می‌کند:

1. **فاز A — پروب موازی TCP handshake delay (`parallelTcpProbe`):** ۱۲ سوکت همزمان روی `Dispatchers.IO` به هر کاندید وصل می‌شوند و تاخیر handshake را اندازه می‌گیرند. این کار JNI-safe است چون هر `Socket` یک نمونه مستقل است.
2. **فاز B — پروب سری Xray HTTP روی برترین بازماندگان:** کاندیدهای زنده بر اساس تاخیر TCP مرتب و فقط `SCANNER_NATIVE_CANDIDATE_LIMIT` کاندید برتر از طریق هسته Xray تست می‌شوند. چون فاز A میزبان‌های مرده را فیلتر کرده، فاز B در کسری از زمان قبلی تمام می‌شود.

روی دسکتاپ، اسکنر از `ThreadPoolExecutor` با تا ۲۸ worker موازی استفاده می‌کند و هر پروب یک فرآیند `xray` مستقل است که از طریق یک پورت محلی تست می‌شود. v2.0.2 سقف صف پروب را از ۷۲ به ۱۲۰ افزایش داد تا workerها در اسکن‌های سنگین کاملاً اشغال بمانند.

**اثر خالص روی یک اسکن ۴۰ کاندیدی:** فاز A حدود ۳-۵ ثانیه (موازی)، فاز B حدود ۸-۱۵ ثانیه (سری اما فقط روی ۲۰-۳۰ کاندید زنده)، مجموع ۱۵-۲۰ ثانیه به جای ۶۰-۹۰ ثانیه در v2.0.0/2.0.1.

### ذخیره فوری + مودال محاسبه پینگ/لوکیشن

از v2.0.1، دکمه «توقف و ذخیره نتایج» SUB را بلافاصله با پینگ واقعی موجود از فاز probe ذخیره می‌کند. سپس یک مودال نمایش داده می‌شود:

> **«محاسبه پینگ و لوکیشن؟»**
> *N سرور ذخیره شد. آیا می‌خواهید پینگ واقعی و لوکیشن هر سرور را همین‌جا محاسبه کنم؟*

اگر کاربر بپذیرد، یک worker پس‌زمینه (دسکتاپ: `ScannerEnrichThread`، اندروید: `ScannerCoordinator.enrichSavedRecords`) شروع به اجرای پروب موازی TCP + پروب سری Xray + فورس‌ریفرش ژئو روی رکوردهای ذخیره‌شده می‌کند. ردیف‌ها به‌صورت اتمیک به‌روزرسانی می‌شوند و UI در طول این کار پاسخگو می‌ماند. اگر کاربر رد کند، هیچ کار اضافه‌ای انجام نمی‌شود.

این رفتار روی هر چهار پلتفرم یکسان است.

## هسته‌ها

| هسته | Desktop | Android | کاربرد |
|---|:---:|:---:|---|
| **Xray** | ✅ | ✅ | اتصال پیش‌فرض و TUN سراسری. نسخه 26.7.11. |
| **Aether** | ✅ | ✅ | اتصال جایگزین و SOCKS داخلی. |
| **WARP / Usque** | ✅ | ✅ | Cloudflare WARP با ثبت و اجرای محلی. |

هر هسته در زمان Build از ریلیز رسمی بالادست دانلود، با SHA-256 منتشرشده اعتبارسنجی و داخل بسته نهایی بسته‌بندی می‌شود. هیچ هسته‌ای به‌صورت داینامیک از منابع نامعتبر بارگذاری نمی‌شود.

## امنیت

- **ارزیابی امنیتی هر کانفیگ:** هر کانفیگ بر اساس پروتکل، رمزنگاری، transport و آیداد سرور امتیازبندی می‌شود (امن / هشدار / خطرناک). کانفیگ‌های خطرناک با یک نشان قرمز در رابط علامت‌گذاری می‌شوند.
- **بدون تلمتر:** هیچ داده‌ای به هیچ سروری ارسال نمی‌شود. تنظیمات، تاریخچه اسکن و سرورهای ذخیره‌شده همگی به‌صورت محلی در `~/.dicodePing/` (دسکتاپ) یا `getFilesDir()` (اندروید) ذخیره می‌شوند.
- **بدون حساب کاربری:** dicodePing هیچ حسابی نمی‌سازد، هیچ ایمیل نمی‌خواهد و هیچ توکنی ذخیره نمی‌کند.
- **Network Security Config:** اندروید فقط به `api.telegram.org`، `github.com` و سرویس ژئو اعتماد دارد؛ تمام اتصالات دیگر به‌صورت پیش‌فرض مسدود هستند.
- **SBOM:** هر انتشار شامل یک `SBOM.spdx.json` است که مؤلفه‌ها و مجوزهای آن‌ها را فهرست می‌کند.
- **Provenance:** هر انتشار شامل یک `provenance.json` است که SHA کامیت و گردش کار ساخت را ثبت می‌کند.
- **SHA-256SUMS:** هر انتشار شامل یک فایل `SHA256SUMS` است که هش تمام فایل‌ها را شامل می‌شود.

برای گزارش آسیب‌پذیری، به [SECURITY.md](SECURITY.md) مراجعه کنید.

## زبان‌ها و RTL

dicodePing به دو زبان فارسی و انگلیسی موجود است. زبان به‌صورت خودکار از تنظیمات سیستم تشخیص داده می‌شود و می‌توان آن را در تنظیمات تغییر داد. چیدمان فارسی راست‌به‌چپ واقعی است (نه فقط ترجمه متن). فونت پیش‌فرض Vazirmatn است که هم برای فارسی و هم برای انگلیسی خوانا است.

## ساخت از سورس

### پیش‌نیازها

- Python 3.10 یا بالاتر
- Git
- برای دسکتاپ: PySide6، PyInstaller (با `pip install -r requirements-build.txt`)
- برای اندروید: Android Studio یا خط فرمان با JDK 17، Android SDK 36، NDK 27.2.12479018، Go 1.26، Rust stable با `cargo-ndk`

### ساخت دسکتاپ

```bash
# 1. وابستگی‌ها
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt

# 2. آماده‌سازی فونت و هسته
python -m tools.prepare_vazirmatn
python -m tools.prepare_core
python -m tools.prepare_optional_cores

# 3. ساخت بسته نهایی
python tools/build_windows.py   # Windows
python tools/build_linux.py     # Linux
python tools/build_macos.py     # macOS
```

خروجی در پوشه `release/` قرار می‌گیرد. هر Builder فونت و هسته‌های موردنیاز را قبل از PyInstaller آماده می‌کند.

### ساخت Android

```bash
cd dicodePing_android

# Linux/macOS
./build_apk.sh

# Windows
build_apk.bat
```

اسکریپت Build فونت‌های محلی Vazirmatn، Xray، Aether و Usque را آماده، `./gradlew lintStandardRelease assembleStandardRelease` را اجرا و محتوای APK نهایی (شامل هش فونت‌ها و ABIهای ۶۴ بیتی) را کنترل می‌کند. خروجی در `dicodePing_android/release/dicodePing-v*.*.*-android.apk` قرار می‌گیرد.

برای امضای Release، متغیرهای محلی زیر را تنظیم کنید (یا در GitHub Secrets):

```text
ANDROID_KEYSTORE_BASE64   # base64 فایل JKS
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
```

## اعتبارسنجی و تست

قبل از هر انتشار، تمام ولیدیتورها و تست‌ها باید سبز باشند:

```bash
# آماده‌سازی فضای کار
python tools/prepare_build_workspace.py

# اعتبارسنجی نسخه
python tools/verify_version.py --tag v2.0.2

# اعتبارسنجی‌های پایدار
python tools/validate_v202_stable.py
python tools/validate_android_gradle_kts.py
python tools/validate_android_source_references.py
python tools/validate_android_lint_hotfix.py
python dicodePing_android/tools/validate_project.py

# اعتبارسنجی YAML گردش کار
python tools/validate_workflow_yaml.py

# کامپایل
python -m compileall -q app.py app_v200.py dicodeping tools tests

# تست‌ها
python -m pytest -q

# درگاه کیفیت
python tools/quality_gate.py
```

## انتشار یک‌کلیکی

برای انتشار یک نسخه پایدار جدید، فایل ZIP سورس را در یک پوشه جدید Extract و `DEPLOY_RELEASE_200.bat` را اجرا کنید. این ابزار:

1. GitHub CLI را احراز هویت می‌کند.
2. Secretهای امضای Android را بررسی/می‌سازد.
3. مخزن را به‌صورت تمیز Clone می‌کند.
4. فایل‌های نسخه‌های قبلی را پاک می‌کند (RC app files, fix reports, hotfix notes, legacy .bat, `.source-files.txt`).
5. تمام ولیدیتورها و تست‌ها را اجرا می‌کند.
6. کامیت و Push به `main`.
7. تگ نسخه را بازسازی و گردش کار `release.yml` را دیسپچ می‌کند.
8. GitHub Pages را دیپلوی و تأیید می‌کند.
9. تا آماده‌شدن تمام assetهای پلتفرم صبر می‌کند.

برای جزئیات بیشتر، [DEPLOY_RELEASE_200_README_FA.txt](DEPLOY_RELEASE_200_README_FA.txt) را بخوانید.

## عیب‌یابی

### اتصال برقرار نمی‌شود

- مطمئن شوید یک سرور بوت‌استرپ سالم دارید (آیکون سبز در فهرست سرورها).
- اگر از فایروال استفاده می‌کنید، خروجی dicodePing را مجاز کنید.
- روی ویندوز، مطمئن شوید Wintun (داخل بسته) بارگذاری شده — اگر آنتی‌ویروس آن را مسدود کرد، استثنا اضافه کنید.

### اسکنر کند است

- مطمئن شوید از v2.0.2 یا بالاتر استفاده می‌کنید — نسخه‌های قبلی پروب‌های ترتیبی داشتند.
- در تنظیمات، حالت منابع را روی «حرفه‌ای» بگذارید تا workerهای بیشتری اختصاص داده شود.
- روی اندروید، مطمئن شوید دستگاه در حالت ذخیره انرژی نیست.

### فونت فارسی نمایش داده نمی‌شود

- نسخه دسکتاپ فونت را از داخل بسته ثبت می‌کند — نیازی به نصب فونت روی سیستم نیست.
- اگر فونت خراب به نظر می‌رسد، فایل `assets/fonts/Vazirmatn-*.ttf` را با `python -m tools.prepare_vazirmatn` بازسازی کنید.

### APK روی اندروید نصب نمی‌شود

- مطمئن شوید اندروید ۷.۰ (API 24) یا بالاتر دارید.
- «Install unknown apps» را برای مرورگرتان فعال کنید.
- اگر خطای "App not installed" دیدید، نسخه قبلی dicodePing را حذف و دوباره نصب کنید.

### اتصال VPN روی اندروید قطع می‌شود

- در تنظیمات اندروید، dicodePing را از بهینه‌سازی باتری مستثنی کنید.
- اگر شبکه تغییر کرد (Wi-Fi به موبایل)، اتصال را دستی قطع و وصل کنید.

برای گزارش باگ، [Issues](https://github.com/mcodersir/dicodePing/issues) را باز کنید و لاگ اسکنر یا اتصال را ضمیمه کنید.

## حریم خصوصی

dicodePing هیچ داده‌ای به خارج از دستگاه ارسال نمی‌کند. برای جزئیات کامل، [PRIVACY.md](PRIVACY.md) را بخوانید. خلاصه:

- تنظیمات و سرورهای ذخیره‌شده محلی هستند.
- تاریخچه اسکن محلی است.
- هیچ تلمتر، کرش‌ریپورت یا تحلیلی ارسال نمی‌شود.
- کانال‌های تلگرام از طریق VPN بوت‌استرپ کشیده می‌شوند تا IP واقعی شما لو نرود.
- سرویس ژئو فقط IP سرورهای پروکسی را می‌بیند، نه IP شما را.

## مشارکت

مشارکت‌ها خوشامد است! لطفاً قبل از PR بزرگ، یک Issue باز کنید تا در مورد تغییر بحث کنیم.

1. مخزن را Fork کنید.
2. یک شاخه جدید بسازید (`git checkout -b feature/my-feature`).
3. تغییرات را Commit کنید با پیام واضح به فارسی یا انگلیسی.
4. تمام ولیدیتورها و تست‌ها را اجرا کنید (`python -m pytest -q`).
5. PR بزنید.

لطفاً [CONTRIBUTING.md](CONTRIBUTING.md) را بخوانید.

## مجوز

dicodePing تحت مجوز **GPL-3.0** منتشر می‌شود. برای جزئیات، [LICENSE](LICENSE) را بخوانید.

مؤلفه‌های ثالث تحت مجوزهای خودشان منتشر می‌شوند — برای فهرست کامل، [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) را بخوانید. خلاصه:

| مؤلفه | مجوز |
|---|---|
| Xray-core | MPL-2.0 |
| AndroidLibXrayLite | MPL-2.0 |
| Aether | MIT |
| Usque (WARP) | Apache-2.0 |
| Vazirmatn font | OFL-1.1 |
| PySide6 | LGPL-3.0 |
| Material Components for Android | Apache-2.0 |
| Kotlin Coroutines | Apache-2.0 |

## سپاسگزاری‌ها

- تیم [Xray-core](https://github.com/XTLS/Xray-core) برای موتور پروکسی.
- تیم [AndroidLibXrayLite](https://github.com/2dust/AndroidLibXrayLite) برای بسته‌بندی اندروید.
- [Vazirmatn](https://github.com/rastikerdar/vazirmatn) برای فونت فارسی.
- همه کانال‌های تلگرامی که کانفیگ‌های عمومی را منتشر می‌کنند.

---

ساخته‌شده توسط [mcodersir](https://github.com/mcodersir). اگر dicodePing به شما کمک کرد، یک ⭐ روی مخزن بزنید!
