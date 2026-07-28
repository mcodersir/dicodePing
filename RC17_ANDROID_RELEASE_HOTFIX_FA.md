# هات‌فیکس انتشار RC17

این بسته خطای کامپایل Android در `ScannerCoordinator.kt` را برطرف می‌کند. فیلد Repository این کلاس `repo` است، اما نسخه قبلی به شناسه تعریف‌نشده `repository` ارجاع می‌داد و در GitHub Actions با `Unresolved reference: repository` متوقف می‌شد.

همچنین اجرای GitHub Pages در برابر خطاهای موقت شبکه و `TLS handshake timeout` مقاوم شده است:

- هر فرمان GitHub CLI تا پنج بار با تأخیر افزایشی تکرار می‌شود.
- خطای NativeCommandError پاورشل قبل از بررسی exit code دیگر اسکریپت را قطع نمی‌کند.
- کل مرحله Pages در BAT تا سه بار تکرار می‌شود.
- شکست Pages مانع ادامه مانیتورینگ Pre-release نمی‌شود.

اعتبارسنجی جدید `tools/validate_android_source_references.py` در تست محلی، Workflow انتشار و هر دو اسکریپت ساخت APK اجرا می‌شود تا این خطا دوباره وارد Release نشود.
