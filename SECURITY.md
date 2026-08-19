# Security policy

نسخه‌های `3.x` پشتیبانی امنیتی می‌شوند. گزارش آسیب‌پذیری را عمومی نکنید؛ از Security Advisory خصوصی GitHub در مخزن استفاده کنید.

اصول پروژه:

- TLS verification به‌صورت پیش‌فرض اجباری است؛
- دسکتاپ Avalonia/.NET فقط با دسترسی Administrator و پیکربندی TUN اجرا می‌شود؛
- inboundهای desktop فقط روی loopback گوش می‌دهند؛
- فایل‌های موقت کانفیگ با دسترسی محدود ساخته و پس از توقف حذف می‌شوند؛
- runtimeها در CI از release/tag pin‌شده دریافت می‌شوند؛
- URL subscription فقط HTTP(S)، بدون credential در URL و با سقف حجم پذیرفته می‌شود؛
- secret، token، کلید امضا و کانفیگ خصوصی نباید در issue یا log ارسال شود.
