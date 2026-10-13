# حریم خصوصی / Privacy

DicodePing حساب یا سرویس analytics و telemetry اختصاصی ندارد. پروفایل‌ها و تنظیمات روی دستگاه نگهداری می‌شوند. اتصال، تازه‌سازی ساب‌ها و آزمون‌ها با سرور و منابع انتخاب‌شده، ساب پیش‌فرض و مقصد آزمون ارتباط برقرار می‌کنند.

## روباه / Fox

روباه اختیاری است. با انتخاب ورود، ایمیل و مقدار مشتق‌شده از رمز برای احراز هویت به Firefox Accounts متعلق به Mozilla ارسال می‌شوند. **رمز عبور در برنامه ذخیره نمی‌شود.** حساب به Guardian برای وضعیت و مجوز Firefox VPN متصل می‌شود؛ فهرست لوکیشن‌ها از Mozilla Remote Settings دریافت می‌شود. ترافیک انتخاب‌شده از پراکسی Firefox VPN عبور می‌کند و DNS کاربران از همان مسیر به DNS-over-HTTPS ارسال می‌شود.

نشست و توکن تمدید حساب در مخزن محلی رمزگذاری می‌شوند: Android Keystore در اندروید، DPAPI برای کاربر فعلی در ویندوز و AES-GCM با فایل کلید محدود به کاربر فعلی در لینوکس و مک. رمزگذاری محلی جایگزین حفاظت از حساب سیستم عامل نیست. عنوان ساب روباه برای تشخیص حساب شامل ایمیل است و مانند سایر نام‌های ساب در اطلاعات فهرست ذخیره می‌شود. رمز، توکن نشست و توکن پراکسی در فایل پروفایل، لینک ساب و گزارش‌های برنامه نوشته نمی‌شوند.

حذف حساب از بخش روباه، نشست ذخیره‌شده و ساب همان حساب را از این برنامه پاک می‌کند؛ حساب Mozilla را حذف یا همهٔ نشست‌های آن را در سرویس لغو نمی‌کند. خروج از سایر دستگاه‌ها و مدیریت مجوز حساب باید از مسیر رسمی Mozilla انجام شود. انتخاب بین حساب‌ها دستی است؛ برنامه حساب جدید نمی‌سازد.

این اتصال غیررسمی است. سیاست حریم خصوصی و شرایط خود Mozilla دربارهٔ داده‌هایی که به آن ارسال می‌شوند اعمال می‌شود.

## پروفایل‌ها و گزارش‌ها

پروفایل‌ها و ساب‌ها ممکن است اطلاعات محرمانهٔ اتصال داشته باشند. فایل تنظیمات و گزارش‌ها را پیش از اشتراک‌گذاری بررسی کنید. وارد کردن کانفیگ از منابع مورد اعتماد و حفاظت از دستگاه بر عهدهٔ کاربر است.

---

Fox is optional. Mozilla account authentication, entitlement and location requests go to Mozilla; selected traffic goes through its Firefox VPN proxy. Passwords are not stored. Local sessions are encrypted and are excluded from exported profiles, subscription URLs, process arguments and application logs. Removing a local account removes its saved session and managed subscription, not the Mozilla account itself. This unofficial integration is subject to the provider's privacy policy and access restrictions.
