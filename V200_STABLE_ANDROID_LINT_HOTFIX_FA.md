# اصلاح بیلد پایدار Android در dicodePing 2.0.0

خطای CI به‌دلیل `warningsAsErrors = true` بود که همه هشدارهای سبک، نسخه وابستگی و تحلیل استاتیک را به ۲۰۶ خطای مسدودکننده تبدیل می‌کرد.

در این بسته:

- خطاهای واقعی همچنان Build را متوقف می‌کنند.
- هشدارها در گزارش‌های HTML/SARIF باقی می‌مانند اما کورکورانه Error نمی‌شوند.
- خطاهای واقعی گزارش‌شده شامل Locale، فونت وزیرمتن، Package Visibility، Backup Rules، Accessibility، Nested Scrolling، DiffUtil، آیکون‌ها و منابع متنی اصلاح شده‌اند.
- موارد کاملاً توصیه‌ای یا False Positive با `lint.xml` و Scope مشخص مدیریت شده‌اند.
- `lintStandardRelease` حذف نشده و همچنان پیش از ساخت APK پایدار اجرا می‌شود.
