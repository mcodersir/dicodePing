# dicodePing

کلاینت چندسکویی فارسی/انگلیسی برای دریافت، ارزیابی و اتصال به کانفیگ‌های پروکسی با Xray TUN واقعی.

## نسخه فعلی

**2.0.0 RC1** برای Windows، Linux، macOS و Android.

### نکات اصلی 2.0

- فونت **Vazirmatn Regular / Medium / Bold** در زمان Build از بسته رسمی `vazirmatn@33.0.3` دریافت، با SHA-512 منتشرشده در npm اعتبارسنجی و داخل خروجی نهایی بسته‌بندی می‌شود.
- نسخه دسکتاپ فونت را با `QFontDatabase.addApplicationFontFromData()` ثبت و روی کل برنامه اعمال می‌کند؛ بسته معیوب اجازه fallback خاموش به فونت سیستم را ندارد.
- Android به‌جای فونت دانلودی Google Fonts از منابع محلی `res/font` استفاده می‌کند.
- پس از ذخیره اولیه اسکنر در `SUB`، همان سرورها یک بار دیگر آزمایش می‌شوند؛ پینگ واقعی و موقعیت IP تازه‌سازی و تراکنش نهایی دوباره ذخیره می‌شود.
- در دسکتاپ هر کانفیگ دو سنجش مستقل دارد: TCP endpoint و درخواست واقعی از داخل Xray.
- رابط مشترک Windows/Linux/macOS و رابط Android تخت‌تر، کم‌حاشیه‌تر و خواناتر شده‌اند.
- وب‌سایت دانلود، فارسی و ریسپانسیو است و فقط توضیح و دکمه‌های مستقیم پلتفرم‌ها را نشان می‌دهد.

## هسته‌ها

| هسته | Desktop | Android | کاربرد |
|---|---:|---:|---|
| Xray | ✅ | ✅ | اتصال پیش‌فرض و TUN سراسری |
| Aether | ✅ | ✅ | اتصال جایگزین و SOCKS داخلی |
| WARP / Usque | ✅ | ✅ | WARP با ثبت و اجرای محلی |

## اجرای سورس دسکتاپ

```bash
python -m pip install -r requirements.txt
python -m tools.prepare_vazirmatn
python app.py
```

## ساخت بسته‌های دسکتاپ

```bash
python tools/build_windows.py   # Windows
python tools/build_linux.py     # Linux
python tools/build_macos.py     # macOS
```

هر Builder فونت و هسته‌های موردنیاز را قبل از PyInstaller آماده می‌کند.

## ساخت Android

```bash
cd dicodePing_android
./build_apk.sh
```

در Windows:

```bat
cd dicodePing_android
build_apk.bat
```

اسکریپت Build فونت‌های محلی، Xray، Aether و Usque را آماده و محتوای APK نهایی را کنترل می‌کند.

## اعتبارسنجی

```bash
python tools/verify_version.py --tag v2.0.0-rc.1
python tools/validate_v200_rc1.py
python tools/validate_android_gradle_kts.py
python tools/validate_android_source_references.py
python -m compileall -q app.py app_v200_rc1.py dicodeping tools tests
python -m pytest -q
python tools/quality_gate.py
python dicodePing_android/tools/validate_project.py
```

## انتشار یک‌کلیکی

ZIP را در یک پوشه جدید Extract و فایل زیر را اجرا کنید:

```text
DEPLOY_PRERELEASE_200_RC1.bat
```

این ابزار ورود GitHub CLI، بررسی/ساخت Secretهای امضای Android، Clone تمیز، پاک‌سازی فایل‌های نسخه‌های قبلی، اعتبارسنجی، Push، ساخت تگ `v2.0.0-rc.1`، انتشار Pre-release و Deploy صفحه GitHub Pages را انجام می‌دهد.

## اسناد

- [حریم خصوصی](PRIVACY.md)
- [امنیت](SECURITY.md)
- [مجوزها و مؤلفه‌های ثالث](THIRD_PARTY_NOTICES.md)
- [یادداشت انتشار 2.0.0 RC1](docs/releases/v2.0.0-rc.1.md)
