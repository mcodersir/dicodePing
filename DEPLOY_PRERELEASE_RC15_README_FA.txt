dicodePing v1.9.0-rc.15 - راهنمای انتشار
==========================================

فایل اجرا:
DEPLOY_PRERELEASE_RC15.bat

اصلاحات اصلی RC15:
- رفع کرش Android در SubscriptionClient برای URL خالی، خراب یا بدون scheme.
- مهاجرت خودکار تنظیمات خراب RC14 و بازیابی منبع اصلی.
- افزایش Android versionCode به 50 و versionName به 1.9.0-rc.15.
- اجباری شدن آماده‌سازی Aether و Usque داخل build_apk.sh.
- اجرای تست‌های Android قبل از assemble Release.
- بررسی نهایی APK برای وجود libgojni.so، libaether.so و libusque.so در arm64-v8a و x86_64.
- بررسی ELF architecture، اندازه، SHA-256 و assets/bundled_cores.json.

روش انتشار:
1) ZIP را کامل داخل یک پوشه جدید Extract کن.
2) DEPLOY_PRERELEASE_RC15.bat را اجرا کن.
3) پنجره را تا پایان GitHub Actions نبند.

پیش‌نیاز محلی:
- Git for Windows
- Python 3
- دسترسی Push به mcodersir/dicodePing

Secretهای GitHub Actions:
- ANDROID_KEYSTORE_BASE64
- ANDROID_KEYSTORE_PASSWORD
- ANDROID_KEY_ALIAS
- ANDROID_KEY_PASSWORD

خروجی‌های مورد انتظار:
- dicodePing-v1.9.0-rc.15-windows-x64.exe
- dicodePing-v1.9.0-rc.15-linux-x86_64.tar.gz
- dicodePing-v1.9.0-rc.15-macos-arm64.dmg
- dicodePing-v1.9.0-rc.15-macos-x86_64.dmg
- dicodePing-v1.9.0-rc.15-android.apk

اسکریپت قبل از Push، Snapshot قدیمی مخزن را پاک می‌کند، فایل‌های RC15 را کپی
می‌کند، Version Validation، Android Validation، تست‌ها و Quality Gate را اجرا
می‌کند. در صورت شکست هر مرحله چیزی Push نمی‌شود.
