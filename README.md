# dicodePing 1.9.0 RC4 — Existing Release Recovery Hotfix 7

این نسخه خروجی‌ها را مثل Release نسخه `v1.8.0-rc.4` می‌سازد و macOS را نیز اضافه می‌کند.

## ساخت EXE ویندوز

ZIP را در یک مسیر کوتاه استخراج و اجرا کن:

```bat
BUILD_RELEASE_RC4.bat
```

خروجی:

```text
release\dicodePing-v1.9.0-rc.4-windows-x64.exe
```

## ساخت APK امضاشده

متغیرهای keystore را تنظیم کن و اجرا کن:

```bat
BUILD_SIGNED_APK_RC4.bat
```

خروجی:

```text
dicodePing_android\release\dicodePing-v1.9.0-rc.4-android.apk
```

## ساخت همه پلتفرم‌ها

Workflow زیر را در GitHub Actions اجرا کن:

```text
.github/workflows/v1.9.0-rc.4-release.yml
```

Release شامل EXE ویندوز، APK اندروید، tar.gz لینوکس، DMG مک برای arm64 و x86_64، Coreهای مستقل Aether/WARP، سورس، SBOM و SHA256SUMS خواهد بود.

## اجرای مستقیم سورس

```bat
RUN_SOURCE_RC4.bat
```

## انتشار کامل و خودکار روی GitHub

برای Push سورس، ساخت Tag، اجرای GitHub Actions و ایجاد Pre-Release فقط این فایل را اجرا کن:

```bat
DEPLOY_PRERELEASE_RC4.bat
```

این نسخه از **Git for Windows و Git Credential Manager** استفاده می‌کند و به GitHub CLI یا بررسی API Token وابسته نیست. اگر ورود Git روی سیستم ذخیره نشده باشد، مرورگر برای ورود به GitHub باز می‌شود.

اسکریپت شاخه `main` را Clone می‌کند، سورس RC4 را جایگزین و اعتبارسنجی می‌کند، یک فایل Trigger یکتا می‌سازد و Commit را Push می‌کند. سپس Tag زیر را به Commit اصلاح‌شده منتقل می‌کند:

```text
v1.9.0-rc.4
```

اگر Pre-Release قبلاً ساخته شده ولی ناقص باشد، اسکریپت دیگر متوقف نمی‌شود. Workflow همان Release را به‌روزرسانی می‌کند و فایل‌های هم‌نام را جایگزین می‌کند. پایان کار فقط زمانی موفق اعلام می‌شود که اجرای دقیق همان Commit موفق باشد و EXE، APK، Linux و هر دو DMG مک داخل Release موجود باشند. Secrets امضای Android باید از قبل در Repository تنظیم شده باشند.
