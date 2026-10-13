# DicodePing 4.7.0 — روباه، مرحله به مرحله

- اصلاح مسیر Guardian مطابق FoxyVPN: ابتدا دریافت توکن VPN؛ در پاسخ 401/403 فعال‌سازی حساب و یک تلاش مجدد. نمایش اطلاعات حساب دیگر پیش‌شرط دریافت توکن نیست.
- رابط مرحله‌ای روباه در دسکتاپ و اندروید: ورود، تأیید در صورت نیاز، انتخاب کشور و اتصال. مدیریت چند حساب با یک ساب و یک سرور برای هر حساب.
- حفظ نشست واردشده در صورت خطای موقت تازه‌سازی؛ امکان تلاش مجدد بدون واردکردن دوباره رمز.
- اصلاح انتخاب زبان دسکتاپ، برچسب روباه، روش‌های اتصال بیشتر و اسکن کلودفلر. تکمیل متن‌های فارسی و انگلیسی صفحات جدید اندروید.
- راهنما و پیام‌های CLI با `--lang fa` یا `--lang en`؛ ورود روباه در یک جریان تعاملی شامل کد تأیید و انتخاب کشور.
- صفحه دانلود فارسی و انگلیسی، واکنش‌گرا، با دانلود جداگانه دسکتاپ، اندروید و CLI.

## راهنمای اتصال

آیکون روباه بالای برنامه را باز کنید. ایمیل و رمز حساب موزیلا را وارد کنید. اگر سرویس کد تأیید خواست، کد را در مرحله دوم وارد کنید. سپس کشور یا REC را انتخاب کنید و اتصال را بزنید. ساب مدیریت‌شده حساب در فهرست سرورها هم قابل انتخاب است.

خط فرمان: `dicodeping fox login --lang fa`، سپس `dicodeping profiles` و `dicodeping connect <profile-id>`.

رمز ذخیره نمی‌شود؛ نشست‌ها رمزگذاری می‌شوند. سهمیه واقعی از سرویس دریافت می‌شود و به‌صورت ساختگی ۵۰ گیگابایت نمایش داده نمی‌شود. روباه TCP و DNS رمزگذاری‌شده دارد؛ UDP عمومی پشتیبانی نمی‌شود.

## English

Fox now follows FoxyVPN's Guardian activation recovery: mint a VPN pass first, activate on 401/403, then retry once. Account status is metadata rather than an eligibility gate. Desktop and Android use guided sign-in, verification and connection steps. CLI has bilingual help/messages with `--lang fa|en` and guided Fox login. Each account retains one managed subscription profile.

Automated tests cover activation recovery, bounded rejection, quota enforcement and real HTTP/2 relay traffic. A successful sign-in with a personal Mozilla account is not claimed by the build tests.

Fox protocol adapted from FoxyVPN by Vauth (MIT); attribution and licenses accompany the helper.
