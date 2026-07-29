# Android release signing

Android releases for application ID `ir.dicode.ping.client` must use the same private JKS key for every update.

## Public signing identity

- Keystore type: JKS
- Alias: `dicodeping-release`
- Certificate SHA-256:

```text
0A:48:33:17:EE:0B:D0:E2:AE:A4:8D:2B:E7:2C:30:F2:06:D3:CC:EB:3F:17:8E:A1:8C:A2:2A:17:D6:CD:FC:C0
```

The CI workflow rejects an APK when its signing certificate does not match this fingerprint.

## Required GitHub Actions secrets

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

The JKS, passwords, and Base64 payload must never be committed to the repository or attached to a public Release.

## Release output

The Android pipeline produces exactly one universal APK containing:

- `armeabi-v7a`
- `arm64-v8a`
- `x86`
- `x86_64`

Public filename:

```text
dicodePing-v0.1.2-android.apk
```
