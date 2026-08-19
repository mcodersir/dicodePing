# Android build

پروژه به JDK 21، Android SDK 36 و NDK 29 نیاز دارد. دو جزء native باید پیش از Gradle در `apps/android/app/libs` قرار گیرند:

- `libv2ray.aar` از `patterniha/AndroidLibXrayLite` tag `v26.8.19-P` (commit `87cb97f3...`)
- خروجی `hev-socks5-tunnel` commit `0428c4e...`

Workflow رسمی این مراحل را pin کرده و APK universal و ABI-specific را تولید می‌کند. APK محلی debug را می‌توان پس از آماده‌سازی nativeها با فرمان زیر ساخت:

```bash
cd apps/android
./gradlew assembleFdroidDebug
```

امضای release فقط از secretهای repository انجام می‌شود؛ هیچ keystore یا کلید خصوصی نباید commit شود.
