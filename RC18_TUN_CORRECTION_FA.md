# RC18 — اصلاح نهایی اتصال Xray TUN

نسخه قبلی RC18 مسئله را با System Proxy دور زده بود. این اصلاح آن مسیر را حذف می‌کند و اتصال Xray دسکتاپ را دوباره به VPN سراسری TUN تبدیل می‌کند.

## مسیر واقعی اتصال

`Windows / Linux / macOS traffic → Xray TUN inbound → selected Xray outbound → Internet`

## معیار اعلام اتصال

1. باینری Xray و وابستگی TUN پلتفرم آماده می‌شوند.
2. IP سرور روی Route فیزیکی تثبیت می‌شود تا Loop رخ ندهد.
3. Xray با Default Routeهای IPv4 و IPv6 روی TUN اجرا می‌شود.
4. یک SOCKS خصوصی داخل همان Process، سالم‌بودن سرور را بررسی می‌کند.
5. یک درخواست HTTP مستقیم با Proxy/PAC غیرفعال، عبور واقعی ترافیک سیستم از TUN را تأیید می‌کند.
6. فقط بعد از موفقیت هر دو مرحله، وضعیت Connected نمایش داده می‌شود.

## پلتفرم‌ها

- Windows: `wintun.dll` و UAC
- Linux: PolicyKit، `pkexec`، `/dev/net/tun` و iproute2
- macOS: رابط آزاد `utunN` و پنجره رسمی مجوز مدیر

System Proxy فقط برای بازیابی Snapshot به‌جامانده از بسته ناقص قبلی RC18 خوانده می‌شود و در اتصال جدید فعال نمی‌شود.
