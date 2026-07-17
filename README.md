<div align="center">
  <img src="assets/app.png" alt="dicodePing logo" width="128" />

# dicodePing

**کلاینت سریع و متن‌باز Windows و Android برای اتصال مبتنی بر Xray**  
**A fast, open-source Xray connectivity client for Windows and Android**

[![CI](https://github.com/mcodersir/dicodePing/actions/workflows/ci.yml/badge.svg)](https://github.com/mcodersir/dicodePing/actions/workflows/ci.yml)
[![CodeQL](https://github.com/mcodersir/dicodePing/actions/workflows/codeql.yml/badge.svg)](https://github.com/mcodersir/dicodePing/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/mcodersir/dicodePing?display_name=tag)](https://github.com/mcodersir/dicodePing/releases/latest)
[![License](https://img.shields.io/github/license/mcodersir/dicodePing)](LICENSE)

[دانلود آخرین نسخه](https://github.com/mcodersir/dicodePing/releases/latest) ·
[مستندات فارسی](docs/README.fa.md) ·
[English documentation](docs/README.en.md) ·
[صفحه مستندات](https://mcodersir.github.io/dicodePing/)

</div>

---
[URL=https://imgurl.ir/viewer.php?file=m03783_file_000000009de87246968b60bf9a728a01.png][IMG]https://cdn.imgurl.ir/uploads/m03783_file_000000009de87246968b60bf9a728a01.png[/IMG][/URL]

## فارسی

dicodePing یک کلاینت متن‌باز Windows و Android برای مدیریت و اتصال به کانفیگ‌های مبتنی بر Xray است. بررسی نهایی سرورها از داخل مسیر واقعی Xray انجام می‌شود؛ بنابراین باز بودن پورت یا پاسخ ICMP به تنهایی به‌عنوان اتصال سالم در نظر گرفته نمی‌شود.

### امکانات اصلی

- دریافت و مدیریت subscription و کانفیگ‌های پشتیبانی‌شده
- سنجش TCP اولیه و تست واقعی HTTPS از داخل مسیر پراکسی
- انتخاب خودکار سرور بر اساس latency، jitter و سلامت اتصال
- TUN/VPN برای Windows و Android با پشتیبانی IPv4 و IPv6 در Android
- نمایش وضعیت اتصال، پینگ و آمار دانلود و آپلود
- امکان تعریف دامنه‌ها و برنامه‌های خارج از تونل
- رابط فارسی و انگلیسی، حالت روشن و تاریک و انیمیشن‌های سبک
- اجرای عملیات شبکه خارج از thread رابط کاربری
- بررسی نسخه و SHA-256 هسته‌های Xray، Wintun و Android هنگام ساخت

### دانلود و نصب

نسخه آماده را از صفحه [Releases](https://github.com/mcodersir/dicodePing/releases/latest) دریافت کنید:

- **Windows:** `dicodePing-v0.1.2-windows.exe`
- **Android:** `dicodePing-v0.1.2-android.apk`

برای بررسی اصالت فایل‌ها، مقدار آن‌ها را با `SHA256SUMS` همان Release مقایسه کنید.

## English

dicodePing is an open-source Windows and Android client for managing and connecting to Xray-based profiles. Final server validation runs through the actual Xray path instead of relying only on ICMP or an open TCP port.

### Highlights

- Subscription and supported-profile management
- Real HTTPS checks through the active proxy path
- Automatic selection based on latency, jitter, and connection health
- Windows TUN and Android VPN connectivity
- IPv4 and IPv6 routing on Android
- Live connection, latency, download, and upload statistics
- Domain and application bypass controls
- Persian and English interfaces with light and dark themes
- Version-pinned and SHA-256-verified native dependencies

### Downloads

- **Windows:** `dicodePing-v0.1.2-windows.exe`
- **Android:** `dicodePing-v0.1.2-android.apk`

Verify downloaded files using the accompanying `SHA256SUMS` file.

## Build locally

```bash
python -m pip install -r requirements-build.txt
python tools/verify_version.py
python -m unittest discover -s tests -v
python tools/quality_gate.py
```

Windows executable:

```powershell
python tools/build_windows.py
```

Android:

```bash
cd dicodePing_android
./gradlew --no-daemon lint test assembleDebug
```

The Windows build pins Xray-core `26.7.11` and Wintun `0.14.1`. The Android build pins AndroidLibXrayLite `26.6.2`. Native dependencies are downloaded from upstream releases and verified before packaging.

## License and responsibility

The repository's original code is released under the [MIT License](LICENSE). Bundled or downloaded third-party components retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Users remain responsible for applicable laws, network policies, imported profiles, and upstream service terms.
