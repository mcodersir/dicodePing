# DicodePing 3

یک کلاینت چندسکویی Xray و اسکنر هم‌زمان کانفیگ برای Windows، Linux، macOS و Android.

> وضعیت: `3.0.0-pre.5` — پیش‌انتشار کلاینت مستقل TUN-only برای آزمون عمومی. برای شبکه‌های حساس، ابتدا با تعداد کمی کانفیگ آزمایش کنید.

## چرا پینگ این برنامه واقعی است؟

DicodePing عدد ICMP یا زمان اتصال مستقیم به IP سرور را به‌عنوان پینگ کانفیگ نشان نمی‌دهد. برای هر کانفیگ، Xray یک outbound مستقل می‌سازد و برنامه از مسیر SOCKS همان outbound اتصال TLS معتبر و درخواست HTTP واقعی می‌فرستد. نتیجه از چند تلاش محاسبه می‌شود:

- `median`: میانهٔ زمان کامل درخواست از داخل تونل؛
- `jitter`: نوسان بین نمونه‌ها؛
- `loss`: درصد تلاش‌های ناموفق؛
- `score`: امتیاز ترکیبی پایداری و سرعت.

این روش کندتر از fake ping است، اما نشان می‌دهد کانفیگ واقعاً قادر به عبور ترافیک است.

## قابلیت‌ها

- import لینک و subscription برای VMess، VLESS، Trojan، Shadowsocks، SOCKS، HTTP و Hysteria2؛
- پشتیبانی از REALITY، TLS، WebSocket، gRPC، HTTPUpgrade و XHTTP در سازندهٔ Xray؛
- subscription پیش‌فرض ثابت DicodeConfigChecker در کنار منابع دلخواه کاربر؛
- اسکن هم‌زمان bounded، cancellation، حذف تکراری‌ها و مرتب‌سازی بر اساس کیفیت واقعی؛
- کلاینت desktop مستقل Avalonia/.NET با اجرای Administrator و TUN-only؛
- کلاینت Android مبتنی بر VpnService، libv2ray و hev-socks5-tunnel؛
- تنظیمات IPv4-first، DNS over HTTPS و retry مناسب اختلال‌های رایج شبکهٔ ایران؛
- اعتبارسنجی TLS؛ گزینهٔ ناامن به‌طور پیش‌فرض فعال نیست.

## ساب پیش‌فرض

```text
https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt
```

منابع افزوده‌شده توسط کاربر این منبع را حذف یا جایگزین نمی‌کنند.

## اجرا و تست دسکتاپ

پیش‌نیاز: .NET SDK 10.

```bash
dotnet build apps/desktop/v2rayN.Desktop/v2rayN.Desktop.csproj
dotnet run --project apps/desktop/v2rayN.Desktop/v2rayN.Desktop.csproj
```

برای اجرای اتصال، فایل‌های سازگار با سیستم را در `bin/` قرار دهید. بسته‌های Release، Xray و sing-box را با کنترل SHA-256 همراه دارند. اجرای TUN به دسترسی Administrator نیاز دارد.

## Android

سورس native در `apps/android` است. build رسمی در GitHub Actions، `libv2ray.aar` متناظر با AndroidLibXrayLite و کتابخانهٔ TUN را با نسخه‌های pin‌شده آماده می‌کند. برای build محلی راهنمای [Android](docs/ANDROID.md) را ببینید.

## معماری و امنیت

- [معماری](docs/ARCHITECTURE.md)
- [مدل پینگ واقعی](docs/REAL_PING.md)
- [امنیت](SECURITY.md)
- [حریم خصوصی](PRIVACY.md)
- [اجزای شخص ثالث](THIRD_PARTY_NOTICES.md)

## مجوز

GPL-3.0-or-later. بخش Android از PattNG/v2rayNG مشتق شده و attribution کامل در `THIRD_PARTY_NOTICES.md` آمده است. Xray-core به‌صورت runtime جداگانه و تحت MPL-2.0 توزیع می‌شود.
