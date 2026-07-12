# مستندات فارسی dicodePing

[صفحهٔ اصلی](../README.md) · [دانلود Release](https://github.com/mcodersir/dicodePing/releases/latest) · [معماری](ARCHITECTURE.md) · [امنیت](../SECURITY.md) · [مستندات انگلیسی](README.en.md)

## معرفی

dicodePing یک کلاینت متن‌باز برای Windows و Android است که کانفیگ‌های اتصال مبتنی بر Xray را دریافت، ارزیابی، مرتب و اجرا می‌کند. معیار نهایی انتخاب سرور، یک درخواست واقعی از داخل مسیر پراکسی است؛ بنابراین «پورت باز» با «اتصال قابل استفاده» اشتباه گرفته نمی‌شود.

## نسخهٔ فعلی

نسخهٔ `0.1.2` شامل اصلاح کامل نمایش آیکون Windows است. آیکون در چهار سطح اعمال می‌شود:

1. resource چنداندازهٔ فایل EXE؛
2. آیکون سراسری `QApplication` پیش از ساخت پنجره‌ها؛
3. شناسهٔ پایدار `AppUserModelID` برای گروه‌بندی shell؛
4. آیکون native کوچک و بزرگ HWND برای taskbar و Alt+Tab.

## نصب Windows

1. از [آخرین Release](https://github.com/mcodersir/dicodePing/releases/latest) فایل `dicodePing-v0.1.2-windows.exe` را بگیرید.
2. SHA-256 فایل را با `SHA256SUMS` مقایسه کنید.
3. برنامه برای ساخت رابط TUN درخواست Administrator می‌کند.
4. کانفیگ یا subscription خود را وارد و سرور مناسب را انتخاب کنید.

## نصب Android

در Release دو APK منتشر می‌شود:

- `android-debug-signed.apk`: قابل نصب و مناسب استفاده و آزمایش مستقیم؛ با کلید عمومی debug امضا شده است.
- `android-release-unsigned.apk`: خروجی release بدون کلید خصوصی. برای کانال رسمی یا فروشگاه باید با keystore خصوصی مالک پروژه امضا شود.

Android 7 یا بالاتر لازم است. در اولین اجرا، مجوز `VpnService` توسط خود Android نمایش داده می‌شود.

## منطق تست اتصال

فرآیند ارزیابی به‌طور خلاصه:

1. اعتبارسنجی ساختار کانفیگ و آدرس سرور؛
2. TCP pre-check با timeout محدود برای حذف خطاهای واضح؛
3. ساخت مسیر واقعی Xray/SOCKS؛
4. درخواست HTTP/HTTPS سلامت از داخل همان مسیر؛
5. محاسبهٔ latency میانه، jitter و وضعیت شکست؛
6. حذف نتایج ناموفق از انتخاب خودکار و مرتب‌سازی موارد سالم.

این مدل به رفتار کلاینت‌های بالغی مانند v2rayNG و v2rayN نزدیک است و از نمایش ping گمراه‌کننده جلوگیری می‌کند.

## حریم خصوصی و داده‌ها

- تنظیمات و cache به‌صورت محلی ذخیره می‌شوند.
- پروژه telemetry یا حساب کاربری اجباری ندارد.
- subscriptionهای واردشده می‌توانند شامل دادهٔ حساس باشند؛ آن‌ها را در issue یا log عمومی منتشر نکنید.
- جزئیات در [PRIVACY.md](../PRIVACY.md) آمده است.

## ساخت از سورس

### Windows

```powershell
py -m pip install -r requirements-build.txt
py tools/verify_version.py
py -m unittest discover -s tests -v
py tools/quality_gate.py
py tools/build_windows.py
```

### Android

```bash
cd dicodePing_android
chmod +x gradlew
./gradlew --no-daemon lint test assembleDebug assembleRelease
```

هستهٔ Android باید در مسیر مشخص‌شده در README زیرپروژه قرار گیرد. workflow رسمی آن را با نسخه و SHA-256 ثابت دریافت می‌کند.

## عیب‌یابی کوتاه

- **آیکون قدیمی بعد از pin کردن:** نسخهٔ قبلی را از taskbar unpin کنید، Explorer را restart و فایل جدید را دوباره pin کنید. آیکون داخل برنامه و EXE در نسخهٔ 0.1.2 اصلاح شده است.
- **عدم اتصال Windows:** برنامه را با Administrator اجرا کنید و وجود `wintun.dll` و core را بررسی کنید.
- **عدم اتصال Android:** مجوز VPN، محدودیت باتری، Private DNS و تغییر شبکه را بررسی کنید.
- **نتیجهٔ ping ناموفق:** ممکن است پورت باز باشد ولی handshake یا مسیر واقعی ترافیک شکست بخورد؛ log تشخیصی را بررسی کنید.

## راستی‌آزمایی Release

هر Release از GitHub Actions ساخته می‌شود و شامل موارد زیر است:

- `SHA256SUMS`
- `SBOM.spdx.json`
- GitHub artifact attestation مبتنی بر OIDC/Sigstore
- شناسهٔ commit و tag قابل مشاهده در صفحهٔ Release

برای سناریوهای کامل تست، [TEST_MATRIX.md](TEST_MATRIX.md) را ببینید.
