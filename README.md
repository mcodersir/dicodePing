# dicodePing 1.9.0 RC6

RC6 adds real multi-sample scanner verification, full splash-screen preparation on desktop and Android, separated live scanner logs, and corrected RTL/LTR sidebar alignment.

## One-click GitHub pre-release

Extract the source ZIP and run:

```bat
DEPLOY_PRERELEASE_RC6.bat
```

The script uses Git for Windows and Git Credential Manager, pushes the fixed source to `main`, creates or moves `v1.9.0-rc.6`, waits for GitHub Actions, verifies all required assets, and opens the pre-release page.

Expected assets:

- `dicodePing-v1.9.0-rc.6-windows-x64.exe`
- `dicodePing-v1.9.0-rc.6-linux-x86_64.tar.gz`
- `dicodePing-v1.9.0-rc.6-macos-arm64.dmg`
- `dicodePing-v1.9.0-rc.6-macos-x86_64.dmg`
- `dicodePing-v1.9.0-rc.6-android.apk`

## Local commands

Windows source run:

```bat
RUN_SOURCE_RC6.bat
```

Windows EXE build:

```bat
BUILD_RELEASE_RC6.bat
```

Signed Android APK:

```bat
BUILD_SIGNED_APK_RC6.bat
```

Bilingual release notes: `docs/releases/v1.9.0-rc.6.md`.
