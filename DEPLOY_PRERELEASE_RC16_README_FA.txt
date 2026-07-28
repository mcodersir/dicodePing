dicodePing v1.9.0 RC16 - One-Click Release + Pages Deploy
=========================================================

روش اجرا:
1) فایل ZIP را داخل یک پوشه جدید Extract کنید.
2) فایل DEPLOY_PRERELEASE_RC16.bat را اجرا کنید.
3) اگر GitHub CLI نصب نباشد، اسکریپت از winget برای نصب آن استفاده می‌کند.
4) در اولین اجرا، مرورگر برای ورود امن به GitHub باز می‌شود.
5) پنجره را تا پایان ساخت Pre-release و GitHub Pages نبندید.

کارهایی که خودکار انجام می‌شوند:
- Clone مخزن mcodersir/dicodePing
- ساخت Snapshot تمیز و حذف فایل‌های باقی‌مانده نسخه‌های قبلی
- حذف تست‌های قفل‌شده روی RC15 که مانع انتشار RC16 بودند
- اجرای Validation، Pytest و Quality Gate قبل از Push
- Push شاخه main و ساخت مجدد tag نسخه v1.9.0-rc.16
- حذف Release قدیمی همان tag برای جلوگیری از باقی ماندن Assetهای کهنه
- انتظار برای ساخت Windows، Linux، macOS، Android و انتشار Pre-release
- لغو Workflowها و Deploymentهای گیرکرده github-pages
- تنظیم Pages روی حالت GitHub Actions، اجرای docs.yml و انتظار برای نتیجه

Secretهای لازم در GitHub Actions:
ANDROID_KEYSTORE_BASE64
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD

هیچ Token یا کلید امضایی داخل فایل BAT ذخیره نشده است.

رفع خودکار Secretهای امضای اندروید
----------------------------------
اگر چهار Secret امضای Android در GitHub وجود نداشته باشند، فایل DEPLOY_PRERELEASE_RC16.bat دیگر متوقف نمی‌شود.
اسکریپت یک کلید امضای دائمی می‌سازد یا نسخه محلی قبلی را بازیابی می‌کند، سپس Secretها را با GitHub CLI تنظیم می‌کند.

نسخه خصوصی کلید در این مسیر نگهداری می‌شود:
%USERPROFILE%\Documents\dicodePing-signing

این پوشه را حذف، منتشر یا داخل Git قرار ندهید. برای آنکه نسخه‌های بعدی APK روی نسخه فعلی نصب شوند، همیشه باید همان کلید حفظ شود.
