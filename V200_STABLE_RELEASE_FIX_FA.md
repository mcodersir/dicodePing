# dicodePing 2.0.0 Stable Release Fix

این نسخه انتشار پایدار 2.0.0 است و پیش‌انتشار نیست.

اصلاحات خط انتشار:
- رفع شکست کاذب بررسی فونت Android پس از Resource Optimization با تطبیق SHA-256 محتوای فونت‌های داخل APK.
- حذف هشدار منسوخ `android:extractNativeLibs` و نگه‌داشتن تنظیم بسته‌بندی در Gradle DSL.
- رفع هشدارهای Linux PyInstaller با نصب `libxcb-shape0` و حذف گزینه icon نامعتبر برای خروجی Linux.
- سخت‌گیری Lint در Release: هشدارها خطا محسوب می‌شوند.
- انتشار GitHub با تگ `v2.0.0`، `prerelease: false` و Latest Release.
- مانیتور کردن اجرای workflow_dispatch و انتشار پایدار به‌جای فرض کردن رویداد push.
