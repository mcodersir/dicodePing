# dicodePing 1.9.0 RC5

RC5 is the scanner, subscription lifecycle, disconnect-safety and Android compatibility release.

## One-click GitHub pre-release

On Windows, extract the source ZIP and run:

```bat
DEPLOY_PRERELEASE_RC5.bat
```

The deployer uses Git for Windows and Git Credential Manager. It clones `main`, copies and validates RC5, pushes a unique release trigger, updates `v1.9.0-rc.5`, waits for the exact GitHub Actions run, then verifies the five required assets before opening the pre-release page.

Expected release assets:

- `dicodePing-v1.9.0-rc.5-windows-x64.exe`
- `dicodePing-v1.9.0-rc.5-linux-x86_64.tar.gz`
- `dicodePing-v1.9.0-rc.5-macos-arm64.dmg`
- `dicodePing-v1.9.0-rc.5-macos-x86_64.dmg`
- `dicodePing-v1.9.0-rc.5-android.apk`

The Android signing secrets must already exist in Repository Settings > Secrets and variables > Actions:

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

## Local builds

Windows EXE:

```bat
BUILD_RELEASE_RC5.bat
```

Direct source run:

```bat
RUN_SOURCE_RC5.bat
```

Signed Android APK:

```bat
BUILD_SIGNED_APK_RC5.bat
```

## RC5 changes

- Scanner bootstrap uses a real worker completion handshake instead of the old fixed 20-second poll.
- Scanner status, log and throughput metrics adapt to narrow windows and do not show an ETA.
- Each scan atomically replaces one local subscription named `SUB`.
- `SUB` servers appear immediately in the Servers page and are removed together when the source is deleted from Settings > Sources.
- Desktop disconnect and shutdown do not delete a running `QThread` or perform duplicate blocking core teardown on the UI thread.
- Sidebar icon/text alignment follows RTL and LTR direction.
- Android targets API 36 with AGP 8.10.1/Gradle 8.11.1, publishes only `arm64-v8a` and `x86_64`, uses modern native-library packaging and serializes JNI lifecycle operations.
- CI checks the signed APK for 16 KiB zip alignment and rejects 32-bit native ABIs.

See `docs/releases/v1.9.0-rc.5.md` for release notes and `VALIDATION_RESULTS_RC5.txt` for the local validation summary.
