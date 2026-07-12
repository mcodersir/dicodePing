# dicodePing Android v0.1.2

نسخهٔ بومی Android با Kotlin، Material و `VpnService`؛ نام و هویت محصول در رابط فارسی و انگلیسی **dicodePing** است.

## ویژگی‌های اصلی

- اجرای Xray در مسیر VPN/TUN اندروید
- سنجش واقعی outbound با AndroidLibXrayLite به‌جای انتخاب بر اساس ICMP
- پیش‌آزمون TCP محدود فقط برای حذف خطاهای واضح
- مسیر پیش‌فرض IPv4 و IPv6 داخل VPN و رفتار fail-closed برای جلوگیری از bypass
- دریافت و مدیریت subscriptionهای متعدد
- انتخاب خودکار یا دستی سرور
- مسیر مستقیم دامنه‌ها و bypass برنامه‌های انتخاب‌شده
- رابط فارسی RTL و انگلیسی LTR، تم روشن/تیره و فهرست‌های بهینه‌شده
- مدیریت تغییر شبکه، lifecycle سرویس، مجوز VPN و پاک‌سازی interface

## پیش‌نیاز ساخت

- JDK 17
- Android SDK 35
- Gradle Wrapper پروژه
- AndroidLibXrayLite `26.6.2` در مسیر زیر:

```text
local-maven/ir/dicode/local/libv2ray/26.6.2/libv2ray-26.6.2.aar
```

دارایی رسمی:

```text
https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.6.2/libv2ray.aar
```

SHA-256 مورد انتظار:

```text
367d6b2f74e62c974c61210c56802127812be4c9410a83a6b8b6cac765a7595e
```

workflow اصلی مخزن فایل را دریافت و پیش از Gradle هش آن را کنترل می‌کند.

## ساخت محلی

Linux/macOS:

```bash
./tools/prepare_core.sh /path/to/libv2ray.aar
./gradlew --no-daemon lint test assembleDebug assembleRelease
```

Windows:

```bat
prepare_core.bat "C:\path\to\libv2ray.aar"
gradlew.bat --no-daemon lint test assembleDebug assembleRelease
```

خروجی debug با کلید عمومی debug قابل نصب است. خروجی release تا زمانی که با keystore خصوصی مالک امضا نشود، unsigned باقی می‌ماند؛ هیچ کلید خصوصی در مخزن یا GitHub Actions نگه‌داری نمی‌شود.

## Release رسمی

workflow ریشهٔ `.github/workflows/release.yml` تنها مرجع انتشار است. با tag نسخه، Android lint/tests اجرا و دو فایل زیر ساخته می‌شوند:

- `dicodePing-v0.1.2-android-debug-signed.apk`
- `dicodePing-v0.1.2-android-release-unsigned.apk`

مجوزها و منشأ هسته در [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) ثبت شده‌اند.
