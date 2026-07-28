dicodePing v1.9.0-rc.14 - راهنمای انتشار در GitHub
====================================================

فایل اصلی:
DEPLOY_PRERELEASE_RC14.bat

روش استفاده:
1) ZIP را کامل Extract کن؛ فایل BAT را داخل ZIP اجرا نکن.
2) مطمئن شو Git for Windows و Python 3 نصب هستند.
3) در GitHub، قسمت Settings > Secrets and variables > Actions این Secretها باید از قبل وجود داشته باشند:
   ANDROID_KEYSTORE_BASE64
   ANDROID_KEYSTORE_PASSWORD
   ANDROID_KEY_ALIAS
   ANDROID_KEY_PASSWORD
4) روی DEPLOY_PRERELEASE_RC14.bat دوبار کلیک کن.
5) اگر GitHub لاگین نباشد، Git Credential Manager صفحه ورود مرورگر را باز می‌کند.
6) اسکریپت سورس تمیز RC14 را روی main می‌فرستد، تگ v1.9.0-rc.14 را ایجاد یا جایگزین می‌کند و تا ساخته‌شدن فایل‌های Release منتظر می‌ماند.

فایل‌هایی که GitHub Actions می‌سازد:
- dicodePing-v1.9.0-rc.14-windows-x64.exe
- dicodePing-v1.9.0-rc.14-linux-x86_64.tar.gz
- dicodePing-v1.9.0-rc.14-macos-arm64.dmg
- dicodePing-v1.9.0-rc.14-macos-x86_64.dmg
- dicodePing-v1.9.0-rc.14-android.apk

نکات مهم:
- هیچ توکن GitHub یا کلید امضا داخل BAT ذخیره نشده است.
- احراز هویت Git از Git Credential Manager ویندوز استفاده می‌کند.
- فایل‌های قدیمی RC، BATهای اضافی، خروجی build، APK، کلیدها و فایل‌های موقت به مخزن منتقل نمی‌شوند.
- اگر تگ RC14 قبلاً وجود داشته باشد، اسکریپت آن را به Commit جدید منتقل می‌کند و Release موجود توسط workflow به‌روزرسانی می‌شود.
- اگر Actions خطا داد، همان صفحه‌ای که اسکریپت باز می‌کند را بررسی کن؛ معمولاً نبودن Secretهای امضای Android اولین علت است.
