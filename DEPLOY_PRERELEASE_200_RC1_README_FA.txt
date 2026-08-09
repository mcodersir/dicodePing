dicodePing 2.0.0 RC1 - Release Network Hotfix

1) ZIP را در یک پوشه کاملا جدید Extract کنید.
2) DEPLOY_PRERELEASE_200_RC1.bat را اجرا کنید.
3) اگر اتصال GitHub هنگام Push، ساخت Tag یا اجرای Workflow موقتا قطع شود، اسکریپت تا 8 مرتبه با Backoff تلاش می‌کند.
4) Tag از طریق GitHub Git References API ساخته و SHA آن با Commit پوش‌شده تطبیق داده می‌شود.
5) release.yml به صورت صریح روی همان Tag اجرا می‌شود؛ بنابراین قطع موقت git push مرحله انتشار را نیمه‌کاره رها نمی‌کند.

فونت‌های تولیدشده در سورس ذخیره نشده‌اند؛ Workflow هنگام Build بسته رسمی Vazirmatn 33.0.3 را دریافت، اعتبارسنجی و داخل خروجی‌ها قرار می‌دهد.
