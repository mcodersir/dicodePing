dicodePing v1.9.0-rc.14 - راهنمای انتشار اصلاح شده v2
=======================================================

فایل اصلی:
DEPLOY_PRERELEASE_RC14.bat

مشکل نسخه قبلی چه بود؟
پوشه‌ای که BAT از آن اجرا شده بود هنوز فایل‌های تاریخی نسخه‌های قبلی مثل tests\test_v160_rc1.py را داشت. اسکریپت قبلی بعد از کپی، فقط وجود این فایل‌ها را بررسی می‌کرد و در صورت پیدا شدن متوقف می‌شد؛ بنابراین انتشار قبل از تست انجام نمی‌شد.

این نسخه چه کار می‌کند؟
- مخزن main را در یک پوشه موقت Clone می‌کند.
- تمام Snapshot قبلی Git را حذف می‌کند.
- سورس RC14 را کپی می‌کند.
- بعد از کپی، فایل‌های تاریخی test_v*.py، Workflowهای نسخه‌ای و BATهای قدیمی را از پوشه موقت حذف می‌کند.
- پاک شدن فایل‌های قدیمی را دوباره بررسی می‌کند.
- سپس Version Validation، Android Validation، تست‌ها و Quality Gate را اجرا می‌کند.
- فقط در صورت موفق بودن تمام بررسی‌ها Commit و Tag را Push می‌کند.
- تگ v1.9.0-rc.14 را به Commit جدید منتقل می‌کند و تا انتشار Assetها منتظر می‌ماند.

روش استفاده:
1) ZIP را کامل Extract کن. BAT را مستقیماً داخل ZIP اجرا نکن.
2) بهتر است پوشه جدید باشد؛ بااین‌حال نسخه v2 فایل‌های تاریخی باقی‌مانده را در Snapshot موقت پاک می‌کند.
3) Git for Windows و Python 3 باید نصب باشند.
4) در GitHub > Settings > Secrets and variables > Actions این Secretها باید موجود باشند:
   ANDROID_KEYSTORE_BASE64
   ANDROID_KEYSTORE_PASSWORD
   ANDROID_KEY_ALIAS
   ANDROID_KEY_PASSWORD
5) روی DEPLOY_PRERELEASE_RC14.bat دوبار کلیک کن.
6) اگر GitHub لاگین نباشد، Git Credential Manager ورود مرورگر را باز می‌کند.
7) پنجره را تا پایان Build نبند.

خروجی‌های مورد انتظار:
- dicodePing-v1.9.0-rc.14-windows-x64.exe
- dicodePing-v1.9.0-rc.14-linux-x86_64.tar.gz
- dicodePing-v1.9.0-rc.14-macos-arm64.dmg
- dicodePing-v1.9.0-rc.14-macos-x86_64.dmg
- dicodePing-v1.9.0-rc.14-android.apk

نکات:
- هیچ Token یا کلید امضایی داخل BAT ذخیره نشده است.
- اگر pytest نصب نباشد، اسکریپت فقط همان وابستگی را نصب می‌کند.
- اگر Validation محلی شکست بخورد، هیچ چیزی به GitHub Push نمی‌شود.
- اگر RC14 قبلاً Release شده باشد، Release موجود با Build جدید به‌روزرسانی می‌شود.

اصلاح v3:
خطای CI با متن زیر مربوط به BAT نبود:
  ServerService.build_and_save() got an unexpected keyword argument 'preview_progress'
علت این بود که بیلدهای Windows/Linux مستقیماً app.py را بسته‌بندی می‌کردند و
نصب‌کننده‌های Runtime اجرا نمی‌شدند. اکنون هر سه بیلدر دسکتاپ از
app_v190_rc14.py استفاده می‌کنند. همان DEPLOY_PRERELEASE_RC14.bat را دوباره اجرا
کنید؛ تگ RC14 به Commit جدید منتقل می‌شود و Workflow از ابتدا اجرا خواهد شد.
