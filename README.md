# dicodePing

یک کلاینت چندسکویی برای دریافت، ارزیابی و اتصال به کانفیگ‌های پروکسی با رابط فارسی و انگلیسی.

## تست واقعی دوگانه دسکتاپ در RC19

در Windows، Linux و macOS هر کانفیگ یک‌بار با TCP و یک‌بار با درخواست واقعی از داخل Xray تست می‌شود. این دو عدد جداگانه در دو ستون رنگی نمایش داده می‌شوند و فقط نتیجه Xray وضعیت سالم/آنلاین را تعیین می‌کند.

## وضعیت نسخه

**v1.9.0-rc.19** — بازگردانی اتصال سراسری و واقعی Xray TUN در Windows، Linux و macOS.

## امکانات تازه RC19

- ترافیک کل سیستم از مسیر `Xray TUN → سرور انتخاب‌شده → اینترنت` عبور می‌کند؛ System Proxy جایگزین TUN نیست.
- برنامه ابتدا خود سرور را با SOCKS خصوصی داخل Xray بررسی می‌کند و سپس یک درخواست مستقیم بدون Proxy را از Route سراسری TUN عبور می‌دهد.
- Windows همراه `wintun.dll` بسته‌بندی می‌شود و مجوز UAC را خودکار درخواست می‌کند.
- Linux مجوز TUN را با PolicyKit می‌گیرد و HOME و محیط نشست کاربر را حفظ می‌کند.
- macOS از رابط معتبر `utunN` و پنجره رسمی رمز مدیر استفاده می‌کند.
- برای جلوگیری از Loop، Interface خروجی، Source IP و Host Route مستقیم سرور قبل از انتقال Default Route تثبیت می‌شوند.
- قطع اتصال، پردازش Xray، Routeهای موقت، Runtime و رابط TUN را پاک می‌کند.
- قابلیت‌های RC17 شامل ماندگاری SUB اسکنر، دریافت موقعیت، امتیاز امنیت، حالت بهینه/حرفه‌ای و هسته‌های Aether و WARP حفظ شده‌اند.

## سکوها

| سکو | اجرا/بسته‌بندی |
|---|---|
| Windows | Python source و خروجی PyInstaller |
| Linux | Python source و بسته tar.gz |
| macOS | Python source و DMG |
| Android | پروژه Gradle با flavor استاندارد و rooted |

## هسته‌های اتصال

| هسته | Desktop | Android | توضیح |
|---|---:|---:|---|
| Xray | ✅ | ✅ | هسته پیش‌فرض |
| Aether | ✅ | ✅ | در APK برای arm64-v8a و x86_64 قرار می‌گیرد |
| WARP / Usque | ✅ | ✅ | ثبت‌نام با پذیرش شرایط و اجرای SOCKS محلی |
| Psiphon | مشروط | مشروط | فقط با client.config مجاز توزیع |

## اجرای سورس دسکتاپ

```bash
python -m pip install -r requirements.txt
python app.py
```

## Android

```bash
cd dicodePing_android
./gradlew assembleStandardDebug
```

برای بیلد Release باید Xray AAR و باینری‌های امضاشده Aether/Usque طبق اسکریپت‌های `tools/` آماده شوند. اطلاعات کلید امضا نباید در مخزن قرار بگیرد.

در Android، پس از فعال‌کردن Aether یا WARP، کاربر به Home هدایت می‌شود و با دکمه اتصال همان هسته را اجرا می‌کند. مسیر اصلی و HTTP/2 fallback امتحان می‌شوند و برنامه فقط بعد از عبور ترافیک واقعی وضعیت متصل را ثبت می‌کند.

## اسکنر

اسکنر دو وضعیت مستقل نشان می‌دهد: **دریافت کانفیگ‌ها** و **آزمایش سرورها**. پیش‌فیلتر موازی، کانفیگ‌های مرده را قبل از تست سنگین حذف می‌کند. خروجی سالم به‌صورت منبع محلی دائمی ذخیره می‌شود و با بستن برنامه یا به‌روزرسانی منابع اینترنتی حذف نمی‌شود. لاگ زنده فقط خطوط جدید را اضافه می‌کند و بدون پرش، آخرین رویداد را نشان می‌دهد.

## تصاویر Android

<p align="center">
  <img src="docs/screenshots/android-settings-appearance.png" width="260" alt="Android appearance settings">
  <img src="docs/screenshots/android-settings-routing-before.png" width="260" alt="Android app routing settings">
</p>

## کیفیت و امنیت

```bash
python tools/verify_version.py
python -m compileall -q app.py dicodeping shared tools tests
python -m pytest -q
python tools/quality_gate.py
python dicodePing_android/tools/validate_project.py
```

- گزارش آسیب‌پذیری: [SECURITY.md](SECURITY.md)
- حریم خصوصی: [PRIVACY.md](PRIVACY.md)
- مجوزها و مؤلفه‌های ثالث: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## انتشار

برای انتشار کامل RC19 در ویندوز، ZIP را Extract و فایل `DEPLOY_PRERELEASE_RC19.bat` را اجرا کنید. این اسکریپت سورس تمیز را روی `main` می‌فرستد، تگ `v1.9.0-rc.19` را ایجاد یا جایگزین می‌کند و تا انتشار خروجی‌های Windows، Linux، macOS و Android منتظر می‌ماند. راهنمای کوتاه در `DEPLOY_PRERELEASE_RC19_README_FA.txt` قرار دارد.

Workflowهای فعال فقط `ci.yml`، `codeql.yml`، `docs.yml` و `release.yml` هستند. انتشار RC19 با تگ `v1.9.0-rc.19` آغاز می‌شود.

## انتشار یک‌کلیکی RC19

پس از Extract کامل بسته در یک پوشه جدید، `DEPLOY_PRERELEASE_RC19.bat` را اجرا کنید. این ابزار Clone، پاک‌سازی فایل‌های RC قبلی، اعتبارسنجی، Push، ساخت مجدد Tag، انتشار Pre-release و بازیابی GitHub Pages را یکجا انجام می‌دهد. جزئیات در `RC19_RELEASE_DEPLOY_FIX_FA.md` آمده است.
