# dicodePing 3.0.0-pre.3

نسخه ۳ یک بازطراحی کامل رابط و معماری کلاینت است. منبع اصلی Subscription پروژه حفظ شده و لایه رابط هیچ وابستگی مستقیم به processهای هسته ندارد. در دسکتاپ، CoreHost مبتنی بر ServiceLib مسئول import پروفایل، ساخت config، lifecycle هسته، System Proxy، TUN، Real Ping، آمار و log است. Android همین مرزبندی را با bridge سازگار Xray پیاده می‌کند.
