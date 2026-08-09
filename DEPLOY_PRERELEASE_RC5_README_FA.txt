dicodePing v1.9.0 RC5 - بازیابی و تکمیل خودکار Pre-Release

فقط فایل زیر را اجرا کنید:

DEPLOY_PRERELEASE_RC5.bat

این فایل از Git for Windows و Git Credential Manager استفاده می‌کند و توکن را داخل BAT یا مخزن ذخیره نمی‌کند. اگر ورود GitHub ذخیره نشده باشد، پنجره ورود مرورگر باز می‌شود.

عملیات خودکار:
- آخرین شاخه main را در پوشه موقت Clone می‌کند.
- سورس اصلاح‌شده و جداسازی صحیح Android product flavorها را بررسی می‌کند.
- در هر اجرا یک Release Trigger یکتا می‌سازد و روی main پوش می‌کند.
- اگر Tag یا Pre-Release قبلی وجود داشته باشد، متوقف نمی‌شود.
- Tag v1.9.0-rc.5 را به Commit اصلاح‌شده منتقل می‌کند.
- Workflow چندپلتفرمی را اجرا می‌کند.
- Release موجود را درجا به‌روزرسانی و فایل‌های هم‌نام را جایگزین می‌کند.
- فقط بعد از موفقیت همان Commit و وجود EXE، APK، Linux و دو DMG مک موفق اعلام می‌کند.

پیش‌نیازهای ویندوز:
- Git for Windows همراه Git Credential Manager
- Python برای اعتبارسنجی محلی Android
- Secrets امضای APK که از قبل در Repository تنظیم شده‌اند

خروجی مورد انتظار:
- dicodePing-v1.9.0-rc.5-windows-x64.exe
- dicodePing-v1.9.0-rc.5-linux-x86_64.tar.gz
- dicodePing-v1.9.0-rc.5-macos-arm64.dmg
- dicodePing-v1.9.0-rc.5-macos-x86_64.dmg
- dicodePing-v1.9.0-rc.5-android.apk
