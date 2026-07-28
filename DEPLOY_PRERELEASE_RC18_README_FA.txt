dicodePing v1.9.0 RC18 - Full TUN Release Deploy
=================================================

روش اجرا:
1) ZIP را داخل یک پوشه کاملاً جدید Extract کنید.
2) فایل DEPLOY_PRERELEASE_RC18.bat را اجرا کنید.
3) اگر GitHub CLI نصب نباشد، اسکریپت از winget برای نصب آن استفاده می‌کند.
4) در اولین اجرا، مرورگر برای ورود امن GitHub باز می‌شود.
5) پنجره را تا پایان ساخت Pre-release و GitHub Pages نبندید.

کارهای خودکار:
- Clone مخزن mcodersir/dicodePing و ساخت Snapshot تمیز RC18
- حذف تست‌ها و فایل‌های انتشار قفل‌شده روی RCهای قدیمی
- بررسی اجباری Xray TUN، Route سراسری IPv4/IPv6 و تست مستقیم بدون Proxy
- بررسی Wintun و UAC در Windows، PolicyKit در Linux و utun در macOS
- اجرای Validation، Pytest و Quality Gate قبل از Push
- Push شاخه main و ساخت مجدد tag نسخه v1.9.0-rc.18
- حذف Release قدیمی همان tag برای جلوگیری از Assetهای کهنه
- انتظار برای ساخت Windows، Linux، macOS و Android و انتشار Pre-release
- بازیابی و استقرار مجدد GitHub Pages با Retry

Secretهای لازم Android در صورت نبود، توسط اسکریپت ساخته یا از نسخه محلی
قبلی بازیابی می‌شوند. نسخه خصوصی کلید در این مسیر باقی می‌ماند:

%USERPROFILE%\Documents\dicodePing-signing

این پوشه را حذف، منتشر یا داخل Git قرار ندهید.
