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
[صفحهٔ مستندات](https://mcodersir.github.io/dicodePing/)

</div>

---

## فارسی

dicodePing برای انتخاب سرور فقط به ICMP یا بازشدن پورت اکتفا نمی‌کند. تست واقعی اتصال از داخل مسیر SOCKS/Xray انجام می‌شود تا سروری انتخاب شود که عملاً توان عبور ترافیک را دارد. رابط ویندوز با PySide6 و نسخهٔ Android با Kotlin ساخته شده‌اند.

### امکانات اصلی

- دریافت و مدیریت subscription و کانفیگ‌های پشتیبانی‌شده
- سنجش TCP اولیه و تست HTTPS واقعی از داخل مسیر پراکسی
- انتخاب خودکار سرور بر اساس latency، jitter و سلامت اتصال
- TUN/VPN برای Windows و Android، همراه با مسیر IPv6 در Android
- رابط فارسی و انگلیسی، حالت روشن و تاریک و انیمیشن‌های سبک
- اجرای عملیات شبکه خارج از thread رابط کاربری
- ساخت خودکار EXE و APK با GitHub Actions
- انتشار SHA-256، SBOM با قالب SPDX و GitHub artifact attestation
- آیکون یکسان در EXE، taskbar، Alt+Tab و پنجرهٔ Windows

### نصب

نسخهٔ آماده را از صفحهٔ [Releases](https://github.com/mcodersir/dicodePing/releases/latest) دریافت کنید:

- **Windows:** فایل `dicodePing-v0.1.2-windows.exe`
- **Android قابل نصب:** فایل `dicodePing-v0.1.2-android-debug-signed.apk`
- **Android release unsigned:** برای امضای نهایی با کلید خصوصی مالک پروژه

برای بررسی اصالت فایل، `SHA256SUMS` همان Release را بررسی کنید. جزئیات کامل در [مستندات فارسی](docs/README.fa.md) آمده است.

## English

dicodePing does not treat ICMP or a successful TCP socket as proof that a profile works. It performs the final health check through the actual SOCKS/Xray path, then ranks usable servers by latency, jitter, and failure state.

The Windows client is built with PySide6; the Android client is native Kotlin. GitHub Actions builds both platforms and publishes checksums, an SPDX SBOM, and artifact attestations.

See the [English documentation](docs/README.en.md), [security policy](SECURITY.md), and [latest release](https://github.com/mcodersir/dicodePing/releases/latest).

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

The Windows build pins Xray-core `26.7.11` and Wintun `0.14.1`. The Android build pins AndroidLibXrayLite `26.6.2` as described in [`dicodePing_android/README.md`](dicodePing_android/README.md). CI downloads each native dependency from its upstream release and verifies SHA-256 before packaging.

## License and responsibility

The repository's original code is released under the [MIT License](LICENSE). Bundled or downloaded third-party components retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Users remain responsible for applicable laws, network policies, imported profiles, and upstream service terms.
