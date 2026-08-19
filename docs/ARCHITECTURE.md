# معماری DicodePing 3

## مرزها

```text
UI مشترک
  ├─ Client: انتخاب، اتصال، وضعیت
  ├─ Scanner: import، تست هم‌زمان، رتبه‌بندی
  └─ Sources: ساب اصلی + ساب‌های کاربر
       │
Core مشترک
  ├─ parser / dedup / subscription
  ├─ Xray config builder
  └─ median / jitter / loss scoring
       │
Runtime platform
  ├─ Desktop: Electron host → Xray process → SOCKS/HTTP loopback
  └─ Android: Compose → libv2ray → VpnService → hev TUN
```

UI هیچ باینری شبکه‌ای را مستقیم اجرا نمی‌کند. در desktop فقط فرایند main اجازهٔ اجرای Xray و دسترسی شبکه دارد؛ renderer با `contextIsolation` و CSP اجرا می‌شود. Android از سرویس foreground و مجوز استاندارد VpnService استفاده می‌کند.

## هم‌زمانی

Scanner پروفایل‌ها را در batchهای کوچک به یک Xray می‌دهد. هر inbound SOCKS فقط به outbound متناظر route می‌شود؛ بنابراین نتایج با یکدیگر مخلوط نمی‌شوند. تعداد batch و تلاش‌ها محدود است تا هزار کانفیگ باعث ساخت هزار process یا اشباع socket نشود.

## وضعیت ایران

- query strategy پیش‌فرض IPv4-first است ولی IPv6 حذف نشده؛
- endpointهای probe از چند ارائه‌دهنده انتخاب می‌شوند؛
- timeout از TCP کوتاه‌تر نیست و برای packet loss متوسط سه تلاش انجام می‌شود؛
- نتیجه با median محاسبه می‌شود تا یک spike رتبه‌بندی را خراب نکند؛
- DNSهای DoH و fallback عددی وجود دارند؛
- هیچ `allowInsecure` عمومی در کانفیگ تولیدشده فعال نمی‌شود.

## محدودیت پیش‌انتشار

در desktop نسخهٔ فعلی SOCKS و HTTP محلی را ارائه می‌دهد. اعمال system proxy/TUN به‌دلیل تفاوت سطح دسترسی سیستم‌عامل‌ها باید در هر پلتفرم جداگانه QA شود و در prerelease بعدی پس از تست installer فعال می‌شود. Android از VpnService واقعی استفاده می‌کند.
