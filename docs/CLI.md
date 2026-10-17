# DicodePing CLI 4.6.0

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

`ping` درخواست واقعی شبکه می‌فرستد. `connect --best` پیش از انتخاب سرور، آزمون تازه انجام می‌دهد؛ اتصال نیز پس از بررسی ترافیک از هستهٔ فعال تأیید می‌شود. برای توقف اتصال `Ctrl+C` بزنید. نتیجهٔ شکست با کد خروج غیرصفر برمی‌گردد. خروجی فهرست و اسکن به صورت JSON است.

گزینهٔ `--tun` برای اتصال کل سیستم به دسترسی مدیر نیاز دارد. `--system-proxy` پراکسی سیستم را برای همین نشست فعال و هنگام خروج پاک می‌کند. در حالت `run` تنظیمات JSON هسته عیناً اجرا می‌شوند؛ تنها فایل معتبر و مورد اعتماد خودتان را وارد کنید. این فرمان با ابزار بومی هسته فایل را اجرا می‌کند و نیازی به بازکردن رابط گرافیکی ندارد.

فرمان `scan-cf` تنها IPهای فایلی که به آن می‌دهید را آزمایش می‌کند، با درخواست HTTPS و اعتبارسنجی گواهی؛ نتیجهٔ موفق به معنای کارکرد همهٔ پروتکل‌ها و سرورها روی آن IP نیست.

Snell، AnyTLS، SSH، OpenVPN و Cisco/OpenConnect از طریق JSON بومی sing-box قابل اجرا هستند. OpenVPN با گواهی کاربر، کلید یا tls-crypt به همان تنظیمات تکمیلی سرور در JSON نیاز دارد. IKEv2 و ابزارهای DNS/HTTP مستقل، هستهٔ داخلی CLI محسوب نمی‌شوند. اطلاعات حساس فایل کانفیگ و پروفایل‌ها را منتشر نکنید.

## Fox / روباه (4.6.0)

`dicodeping fox login` prompts privately for your Mozilla account email and password. If verification is required, run `dicodeping fox verify <account-id>` and enter the code. Passwords are never stored; session tokens stay in the encrypted account vault. Do not put passwords or codes in command arguments.

- `fox accounts`: account IDs, email, location and provider-reported allowance; no tokens.
- `fox locations`: currently available provider locations.
- `fox refresh <id>`: refresh account allowance and its single managed subscription profile.
- `fox location <id> <REC|CC>`: save recommended selection or a country code such as `DE`.
- `fox remove <id>`: delete the local account and its subscription.

Use `profiles` to find its profile ID, then `connect <profile-id>` for the foreground session. Account selection is manual. The Fox route supports TCP and encrypted DNS, not arbitrary UDP. Eligibility and allowance are controlled by Mozilla; this is an unofficial integration. Deleted subscriptions return only after explicit synchronization.

برای آمار واقعی ترافیک از `connect <id> --stats` استفاده کنید؛ خروجی JSON هر ثانیه، سرعت و مجموع مصرف را با واحد KiB نشان می‌دهد.
Use `connect <id> --stats` for live JSON upload/download rates and accumulated KiB traffic.
