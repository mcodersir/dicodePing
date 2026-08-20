# DicodePing 3

<div align="center">
<img width="1672" height="941" alt="image" src="https://github.com/user-attachments/assets/cf8274f6-8361-4c79-b6f3-8e29e435c85d" />

> وضعیت: `3.0.2` — نسخهٔ پایدار کلاینت مستقل TUN-only برای Windows، Linux، macOS و Android.

### یک کلاینت هوشمند Xray برای تست، رتبه‌بندی و استفاده واقعی از کانفیگ‌ها

**Windows • Linux • macOS • Android**

[![Release](https://img.shields.io/github/v/release/mcodersir/dicodePing)](https://github.com/mcodersir/dicodePing/releases)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

</div>

---

## معرفی

**DicodePing** یک کلاینت چندسکویی مبتنی بر Xray است که برای بررسی کیفیت واقعی کانفیگ‌ها، اسکن هم‌زمان، مدیریت اتصال و اجرای تونل امن طراحی شده است.

برخلاف ابزارهایی که فقط IP سرور را Ping می‌کنند، DicodePing مسیر واقعی ترافیک را بررسی می‌کند؛ یعنی هر کانفیگ از داخل تونل خودش تست می‌شود تا مشخص شود آیا واقعاً توانایی عبور ترافیک دارد یا خیر.

> نسخه فعلی: **3.0.2**
> کلاینت مستقل با معماری **TUN-only** برای Desktop و Android

---

# چرا پینگ DicodePing واقعی است؟

بسیاری از ابزارها برای نمایش سرعت کانفیگ فقط یک ICMP Ping یا زمان اتصال TCP به IP سرور را اندازه‌گیری می‌کنند. این مقدار معمولاً کیفیت واقعی یک تونل را نشان نمی‌دهد.

DicodePing برای هر کانفیگ یک مسیر مستقل Xray ایجاد می‌کند و سپس از داخل همان تونل، درخواست واقعی ارسال می‌کند.

نتیجه بر اساس چند معیار محاسبه می‌شود:

* **Median**
  زمان میانه درخواست کامل از داخل تونل

* **Jitter**
  میزان نوسان بین تست‌ها

* **Loss**
  درصد درخواست‌های ناموفق

* **Score**
  امتیاز ترکیبی پایداری و سرعت

این روش نسبت به Fake Ping زمان بیشتری نیاز دارد، اما نتیجه آن نشان می‌دهد یک کانفیگ در شرایط واقعی شبکه چگونه عمل می‌کند.

---

# قابلیت‌ها

## اسکن و مدیریت کانفیگ

* پشتیبانی از:

  * VMess
  * VLESS
  * Trojan
  * Shadowsocks
  * SOCKS
  * HTTP
  * Hysteria2

* Import مستقیم لینک و Subscription

* اسکن هم‌زمان تعداد زیادی کانفیگ

* حذف خودکار موارد تکراری

* مرتب‌سازی بر اساس کیفیت واقعی اتصال

* محاسبه سرعت، پایداری و وضعیت هر کانفیگ

---

## پشتیبانی کامل Xray

پشتیبانی از:

* REALITY
* TLS
* WebSocket
* gRPC
* HTTPUpgrade
* XHTTP

همراه با اعتبارسنجی TLS و جلوگیری از فعال بودن تنظیمات ناامن به‌صورت پیش‌فرض.

---

# Desktop Client

پشتیبانی از:

* Windows
* Linux
* macOS

ویژگی‌ها:

* معماری مستقل Avalonia/.NET
* اجرای TUN بدون نیاز به کلاینت‌های جانبی
* اجرای Administrator برای مدیریت شبکه
* کنترل کامل Proxy و اتصال
* نمایش Log و وضعیت لحظه‌ای

---

# Android Client

نسخه Android بر پایه:

* Android VpnService
* libv2ray
* hev-socks5-tunnel

ساخته شده است.

ویژگی‌ها:

* اجرای مستقیم تونل VPN
* مصرف بهینه منابع
* مدیریت اتصال در پس‌زمینه
* سازگار با ساختار AndroidLibXrayLite

راهنمای ساخت:

[Android Build Guide](https://github.com/mcodersir/dicodePing/blob/main/docs/ANDROID.md)

---

# Subscription پیش‌فرض

DicodePing به‌صورت پیش‌فرض منبع رسمی DicodeConfigChecker را دارد:

```text
https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt
```

منابع اضافه‌شده توسط کاربر مستقل هستند و این منبع را حذف یا جایگزین نمی‌کنند.

---

# نصب و دریافت

آخرین نسخه‌ها:

[Download Releases](https://github.com/mcodersir/dicodePing/releases)

نسخه‌های منتشرشده شامل:

* Desktop Builds
* Android APK
* فایل‌های وابسته Xray
* بررسی SHA-256 فایل‌های runtime

---


# معماری

مستندات فنی:

* [Architecture](https://github.com/mcodersir/dicodePing/blob/main/docs/ARCHITECTURE.md)

* [Real Ping Model](https://github.com/mcodersir/dicodePing/blob/main/docs/REAL_PING.md)

* [Security](https://github.com/mcodersir/dicodePing/blob/main/SECURITY.md)

* [Privacy](https://github.com/mcodersir/dicodePing/blob/main/PRIVACY.md)

* [Third Party Notices](https://github.com/mcodersir/dicodePing/blob/main/THIRD_PARTY_NOTICES.md)

---

# امنیت و حریم خصوصی

DicodePing:

* اطلاعات کانفیگ‌ها را به سرور خارجی ارسال نمی‌کند.
* تست‌ها را از مسیر واقعی هر کانفیگ انجام می‌دهد.
* اجرای TLS ناامن را به‌صورت پیش‌فرض فعال نمی‌کند.
* اجزای runtime را با checksum بررسی می‌کند.

---

# License

این پروژه تحت مجوز:

```
GPL-3.0-or-later
```

منتشر شده است.

بخش Android از پروژه‌های متن‌باز مرتبط با v2rayNG/PattNG مشتق شده و attribution کامل در فایل:

```
THIRD_PARTY_NOTICES.md
```

قرار دارد.

Xray-core به‌صورت runtime جداگانه و تحت مجوز:

```
MPL-2.0
```

استفاده می‌شود.

---

<div align="center">

ساخته شده با تمرکز روی تست واقعی شبکه و تجربه ساده کاربر

**DicodePing**

</div>
