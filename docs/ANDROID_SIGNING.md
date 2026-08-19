# Android release signing — Version 3

Android releases for application ID `ir.dicode.ping.client` must use the same private JKS key for every update. Version 3 never stores private signing material in source control.

## Public signing identity

- Keystore type: JKS
- Alias: `dicodeping-release`
- Certificate SHA-256:

```text
0A:48:33:17:EE:0B:D0:E2:AE:A4:8D:2B:E7:2C:30:F2:06:D3:CC:EB:3F:17:8E:A1:8C:A2:2A:17:D6:CD:FC:C0
```

## Required GitHub Actions secrets

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

The JKS, passwords, and Base64 payload must never be committed or attached to a public release.

## Local build variables

```text
ANDROID_KEYSTORE_PATH
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
```

## Release output

The Version 3 standard pipeline produces one universal APK containing:

- `armeabi-v7a`
- `arm64-v8a`
- `x86_64`

Public filename:

```text
dicodePing-v3.0.0-pre.6-android.apk
```
