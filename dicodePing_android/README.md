# dicodePing Android — v2.0.0

کلاینت بومی Android با Kotlin، Material 3، `VpnService` و AndroidLibXrayLite.

## فونت و رابط 2.0

Build رسمی، Vazirmatn نسخه 33.0.3 را اعتبارسنجی و Regular، Medium و Bold را به‌صورت منابع محلی `res/font` داخل APK قرار می‌دهد. رابط به Google Fonts یا وجود فونت روی گوشی وابسته نیست. کارت‌ها و دکمه‌ها نیز تخت‌تر و کم‌حاشیه‌تر شده‌اند.

## هسته‌ها

## روش اتصال با Aether یا WARP

1. در تنظیمات، هسته را انتخاب و **فعال** کنید.
2. در پیام نمایش‌داده‌شده، **رفتن به صفحه اصلی** را بزنید.
3. در Home دکمه **اتصال** را بزنید و تا پایان مراحل زنده صبر کنید.
4. برنامه فقط بعد از تست واقعی ترافیک، وضعیت «متصل» را نشان می‌دهد.

در اولین اتصال WARP، ثبت دستگاه در همین جریان foreground انجام می‌شود. اگر مسیر اصلی پاسخ ندهد، برنامه به‌صورت خودکار HTTP/2 را امتحان می‌کند.

### معماری اتصال خارجی

```text
Android VpnService / TUN
        ↓
Xray local SOCKS bridge
        ↓
Aether :1819 یا Usque/WARP :1820
        ↓
Internet
```

Xray در این حالت مقصد یا سرور اتصال نیست؛ فقط بسته‌های TUN اندروید را به SOCKS هسته انتخاب‌شده تحویل می‌دهد.

- **Xray:** داخل مسیر اصلی VPN/TUN.
- **Aether 1.4.0:** به‌صورت باینری ELF برای `arm64-v8a` و `x86_64` در APK قرار می‌گیرد و یک SOCKS محلی می‌سازد.
- **WARP / Usque 4.2.1:** داخل APK قرار می‌گیرد؛ پس از پذیرش شرایط، ثبت‌نام انجام می‌شود و SOCKS محلی می‌سازد.
- **Psiphon:** بدون `client.config` مجاز قابل توزیع نیست و رابط برنامه دلیل غیرفعال‌بودن را نمایش می‌دهد.

## پیش‌نیاز

- JDK 17
- Android SDK / compileSdk 36
- Android NDK برای ساخت Usque
- Go برای cross-compile کردن Usque
- AndroidLibXrayLite `26.7.11`

AAR باید در این مسیر قرار بگیرد:

```text
local-maven/ir/dicode/local/libv2ray/26.7.11/libv2ray-26.7.11.aar
```

SHA-256 مورد انتظار:

```text
0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352
```

## آماده‌سازی هسته‌های bundled

نیازی به اجرای دستی مرحله جداگانه نیست. `build_apk.sh` و `build_apk.bat` قبل از Gradle، Aether و Usque را برای هر دو ABI می‌سازند/دریافت می‌کنند و بعد از ساخت نیز خود APK را بررسی می‌کنند. اجرای مستقیم Gradle بدون هسته‌ها با خطا متوقف می‌شود.

## ساخت Debug

```bash
./gradlew --no-daemon assembleStandardDebug
```

## ساخت Release

متغیرهای `ANDROID_KEYSTORE_PATH`، `ANDROID_KEYSTORE_PASSWORD`، `ANDROID_KEY_ALIAS` و `ANDROID_KEY_PASSWORD` را تنظیم کنید و سپس:

```bash
./build_apk.sh
```

در Windows از `build_apk.bat` استفاده کنید. فقط همین اسکریپت عمومی و `gradlew.bat` نگه‌داری شده‌اند؛ اسکریپت‌های نسخه‌ای قدیمی حذف شده‌اند.
