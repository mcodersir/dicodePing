# گزارش اصلاح انتشار و GitHub Pages — RC16

## علت متوقف‌شدن انتشار

فایل‌های تست RC15 در پوشه‌ای که RC16 روی آن Extract شده بود باقی مانده بودند. این تست‌ها عمداً انتظار نسخه، `versionCode`، Entry Point و فایل Deploy مربوط به RC15 را داشتند و پیش‌اعتبارسنجی RC16 را متوقف می‌کردند.

## اصلاح انجام‌شده

- ابزار `tools/purge_stale_release_tests.py` تست‌های نسخه‌ای باقی‌مانده از RCهای قبلی را قبل از Pytest حذف می‌کند.
- تست‌های عمومی قدیمی که به نسخه قبلی قفل نشده‌اند حفظ می‌شوند.
- اسکریپت Deploy قبل از Push نبودن تست‌های RC15 را دوباره کنترل می‌کند.
- Release موجود با همان Tag قبل از انتشار دوباره حذف می‌شود تا Assetهای قدیمی باقی نمانند.
- GitHub CLI، ورود کاربر و Secretهای امضای Android قبل از Clone بررسی می‌شوند.

## اصلاح GitHub Pages

- `actions/upload-pages-artifact@v4`
- `actions/configure-pages@v5`
- `actions/deploy-pages@v4`
- مجوزهای مستقل `pages: write` و `id-token: write`
- بررسی وجود `docs/site/index.html`
- Artifact ثابت با نام `github-pages`
- تنظیم خودکار Pages روی `build_type=workflow`
- لغو Workflowها و Deploymentهای گیرکرده محیط `github-pages`
- اجرای مجدد `docs.yml` و انتظار تا پایان Deployment

## اجرای انتشار

فقط فایل زیر را از ریشه پوشه Extract‌شده اجرا کنید:

```text
DEPLOY_PRERELEASE_RC16.bat
```

## Bootstrap خودکار امضای Android

Deployer دیگر در نبود `ANDROID_KEYSTORE_BASE64` و سه Secret همراه آن متوقف نمی‌شود. ابزار `tools/bootstrap_android_signing.ps1`:

- Secretهای موجود را بررسی می‌کند.
- از نسخه خصوصی محلی، Secretهای ناقص را بازیابی می‌کند.
- در اولین اجرا یک JKS دائمی با RSA-4096 ایجاد می‌کند.
- چهار مقدار سازگار را یک‌جا با `gh secret set --env-file` ثبت می‌کند.
- نسخه خصوصی کلید را خارج از سورس در `Documents/dicodePing-signing` نگه می‌دارد.
- مقدار هیچ Secretی را در خروجی، BAT یا مخزن چاپ و ذخیره نمی‌کند.
