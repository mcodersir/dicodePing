# Changelog

## 3.0.0-pre.3

- Electron از دسکتاپ حذف و کلاینت مستقل Avalonia/.NET مبتنی بر v2rayN 7.24.7 جایگزین شد.
- نام، آیکن، فونت Vazirmatn و ظاهر دسکتاپ با زبان بصری Android DicodePing یکپارچه شدند.
- اجرای دسکتاپ با دسترسی Administrator اجباری و TUN به تنها مسیر اتصال تبدیل شد.
- Subscription پیش‌فرض DicodePing در شروع دریافت می‌شود، تست واقعی اجرا و لیست سریع‌ترین به کندترین مرتب می‌گردد.
- Android: دو FAB مستقل برای اتصال دستی و اتصال هوشمند، فاصلهٔ امن از پنل وضعیت، Location Test بتا و نمایش پرچم اتصال فعال افزوده شد.
- نام placeholder قدیمی `Default` بدون حذف کانفیگ‌های دستی به `Local configs` مهاجرت یافت.

## 3.0.0-pre.2

- بازطراحی کامل رابط دسکتاپ با گردش‌کار group/profile الهام‌گرفته از v2rayN 7.24.7.
- طراحی مینیمال خطی Dicode برای Windows، Linux، macOS و Android.
- لوگوی رسمی جدید در launcher، پنجره و بسته‌های نصب.
- فونت Vazirmatn در تمام رابط‌های دسکتاپ و Android.
- تجمیع و نمایش همه subscriptionها در تب نخست و همگام‌سازی خودکار دسکتاپ.
- FAB سمت راست برای تست واقعی و اتصال خودکار به بهترین کانفیگ.
- کارت‌های کانفیگ، جست‌وجو، گروه‌های ساب، وضعیت اتصال و نتایج اسکن بازطراحی شدند.
- هیچ تغییری در هستهٔ Xray، منطق ساخت کانفیگ یا موتور real-path scanner انجام نشده است.

## 3.0.0-pre.8

- بازنویسی کامل desktop و core؛ هیچ کد runtime نسخه‌های قبلی ادامه داده نشده است.
- هستهٔ import و subscription چندپروتکلی با منبع پیش‌فرض DicodeConfigChecker.
- تست واقعی SOCKS → TLS → HTTP با median، jitter، loss و score.
- Xray batch isolation و اسکن هم‌زمان bounded.
- UI تازهٔ client/scanner/sources برای desktop.
- Android native مبتنی بر PattNG 2.3.4-P26 با برند و ساب DicodePing.
- pipeline چندسکویی برای Windows، Linux، macOS و Android.
