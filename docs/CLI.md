# DicodePing CLI 4.5.0

نسخهٔ مستقل خط فرمان، همراه Xray، sing-box، Mihomo و ابزارهای Aether. فایل مخصوص سیستم خود را باز کنید و `dicodeping` (ویندوز: `dicodeping.exe`) را اجرا کنید. داده‌های CLI در پوشهٔ جدا از رابط گرافیکی نگهداری می‌شوند. با `--data PATH` پوشهٔ دلخواه را انتخاب کنید.

```sh
dicodeping --help
dicodeping import servers.txt
dicodeping profiles
dicodeping refresh
dicodeping ping
dicodeping connect --best
dicodeping connect PROFILE_ID
dicodeping check profile.json --engine sing-box
dicodeping run profile.json --engine sing-box
dicodeping scan-cf cloudflare-ips.txt
```

`ping` درخواست واقعی شبکه می‌فرستد. `connect --best` از نتیجهٔ موفق ذخیره‌شده استفاده می‌کند؛ اگر هیچ نتیجه‌ای موجود نباشد ابتدا آزمون انجام می‌دهد. برای توقف اتصال `Ctrl+C` بزنید. نتیجهٔ شکست با کد خروج غیرصفر برمی‌گردد. خروجی فهرست و اسکن به صورت JSON است.

گزینهٔ `--tun` برای اتصال کل سیستم به دسترسی مدیر نیاز دارد. `--system-proxy` پراکسی سیستم را برای همین نشست فعال و هنگام خروج پاک می‌کند. در حالت `run` تنظیمات JSON هسته عیناً اجرا می‌شوند؛ تنها فایل معتبر و مورد اعتماد خودتان را وارد کنید. این فرمان با ابزار بومی هسته فایل را اجرا می‌کند و نیازی به بازکردن رابط گرافیکی ندارد.

فرمان `scan-cf` تنها IPهای فایلی که به آن می‌دهید را آزمایش می‌کند، با درخواست HTTPS و اعتبارسنجی گواهی؛ نتیجهٔ موفق به معنای کارکرد همهٔ پروتکل‌ها و سرورها روی آن IP نیست.

Snell، AnyTLS، SSH، OpenVPN و Cisco/OpenConnect از طریق JSON بومی sing-box قابل اجرا هستند. OpenVPN با گواهی کاربر، کلید یا tls-crypt به همان تنظیمات تکمیلی سرور در JSON نیاز دارد. IKEv2 و ابزارهای DNS/HTTP مستقل، هستهٔ داخلی CLI محسوب نمی‌شوند. اطلاعات حساس فایل کانفیگ و پروفایل‌ها را منتشر نکنید.
