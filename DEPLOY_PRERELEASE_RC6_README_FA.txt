dicodePing v1.9.0 RC6 - انتشار خودکار Pre-release

فایل زیر را اجرا کنید:

  DEPLOY_PRERELEASE_RC6.bat

اسکریپت با Git for Windows و Git Credential Manager:
- آخرین main را در پوشه موقت Clone می‌کند.
- سورس RC6 را اعتبارسنجی و روی main پوش می‌کند.
- Tag نسخه v1.9.0-rc.6 را ایجاد یا به Commit جدید منتقل می‌کند.
- Workflow چندپلتفرمی را اجرا می‌کند.
- تا پایان Build ویندوز، لینوکس، دو نسخه مک و APK اندروید منتظر می‌ماند.
- وجود هر پنج فایل Release را بررسی و صفحه Pre-release را باز می‌کند.

در صورت باز شدن صفحه ورود GitHub، همان حساب مالک مخزن را تأیید کنید.
توکن در BAT ذخیره نشده و نیازی به GitHub CLI نیست.
