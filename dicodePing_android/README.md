# dicodePing Android — Version 3 pre-release

Android is the native mobile target of dicodePing V3. It keeps the same authoritative dicodePing subscription ecosystem and uses a platform-native `VpnService` integration behind the same product-layer concepts as desktop.

## Runtime

- Kotlin + Material 3
- Android `VpnService` / TUN
- Pinned Xray-compatible native Android proxy runtime `26.7.11`
- One networking path only: the packaged Android Xray runtime
- Universal APK for `arm64-v8a`, `armeabi-v7a`, and `x86_64`

Prepare the pinned AAR with `../PREPARE_V3_RUNTIME.bat` (or `python ../tools/fetch_runtime_assets.py --android`). It is installed at:

```text
local-maven/ir/dicode/local/libv2ray/26.7.11/libv2ray-26.7.11.aar
```

Expected SHA-256:

```text
0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352
```

## Build

Requirements: JDK 17 and Android SDK with compileSdk 36. Release signing uses these environment variables only:

```text
ANDROID_KEYSTORE_PATH
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
```

Linux/macOS:

```bash
./build_apk.sh
```

Windows:

```bat
build_apk.bat
```

The build validates the pinned runtime, bundled fonts, ABI coverage and release output before accepting the APK.
