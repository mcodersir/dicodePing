# dicodePing

یک کلاینت چندسکویی برای دریافت، ارزیابی و اتصال به کانفیگ‌های پروکسی با رابط فارسی و انگلیسی.

## وضعیت نسخه

**v1.9.0-rc.17** — اتصال و لغو واقعی Aether/WARP، ماندگاری دائمی خروجی اسکنر، تست سریع‌تر سرورها و لاگ زنده بدون پرش در Android، Windows، Linux و macOS.

## امکانات تازه RC17

- هنگام ذخیره خروجی اسکنر، IP و موقعیت تقریبی شامل کشور، شهر، ISP و ASN با محدودیت زمانی کوتاه دریافت و همراه همان SUB به‌صورت دائمی ذخیره می‌شود.
- هر سرور یک امتیاز توضیحی **سطح امنیت** دارد که از نشانه‌های قابل مشاهده کانفیگ مانند TLS/Reality، SNI، نوع انتقال و `allowInsecure` محاسبه می‌شود. این امتیاز ممیزی یا تضمین اعتماد به صاحب سرور نیست.
- حالت مصرف منابع **بهینه** به‌صورت پیش‌فرض فعال است و تعداد Workerها را با CPU و RAM دستگاه هماهنگ می‌کند. حالت **حرفه‌ای** از تنظیمات قابل فعال‌سازی است و سقف‌های بالاتری، اما همچنان محدود، دارد.
- Aether اندروید از Snapshot پین‌شده پروژه `QW-AI-Code/Aether` بیلد می‌شود؛ در دسکتاپ نیز مالکیت پردازش، توقف، تشخیص پورت SOCKS و fallback از الگوهای عملی Aether-GUI پیروی می‌کنند.
- کارت‌های سرور و مرحله ذخیره موقعیت در Android و Desktop واضح‌تر شده‌اند.

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

برای انتشار کامل RC17 در ویندوز، ZIP را Extract و فایل `DEPLOY_PRERELEASE_RC17.bat` را اجرا کنید. این اسکریپت سورس تمیز را روی `main` می‌فرستد، تگ `v1.9.0-rc.17` را ایجاد یا جایگزین می‌کند و تا انتشار خروجی‌های Windows، Linux، macOS و Android منتظر می‌ماند. راهنمای کوتاه در `DEPLOY_PRERELEASE_RC17_README_FA.txt` قرار دارد.

Workflowهای فعال فقط `ci.yml`، `codeql.yml`، `docs.yml` و `release.yml` هستند. انتشار RC17 با تگ `v1.9.0-rc.17` آغاز می‌شود.

## انتشار یک‌کلیکی RC17

پس از Extract کامل بسته در یک پوشه جدید، `DEPLOY_PRERELEASE_RC17.bat` را اجرا کنید. این ابزار Clone، پاک‌سازی فایل‌های RC قبلی، اعتبارسنجی، Push، ساخت مجدد Tag، انتشار Pre-release و بازیابی GitHub Pages را یکجا انجام می‌دهد. جزئیات در `RC17_RELEASE_DEPLOY_FIX_FA.md` آمده است.
