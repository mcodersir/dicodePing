# dicodePing 1.9.0 RC4 — Git Deploy Hotfix 5

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

اسکریپت به‌ترتیب شاخه `main` را Clone می‌کند، سورس RC4 را جایگزین می‌کند، Commit را Push می‌کند و Tag زیر را می‌فرستد:

```text
v1.9.0-rc.4
```

Push شدن Tag، Workflow چندپلتفرمی را خودکار اجرا می‌کند. در پایان، Pre-Release شامل EXE، APK، Linux و دو خروجی macOS ساخته می‌شود. Secrets امضای Android باید از قبل در Repository تنظیم شده باشند.
