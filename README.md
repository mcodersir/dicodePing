# dicodePing 1.9.0 RC7

RC7 fixes automatic best-server selection, tests a deterministic 30% sample from every subscription during splash startup, and stabilizes the sidebar and settings layout across Windows, Linux and macOS.

## One-click GitHub pre-release

Run:

```bat
DEPLOY_PRERELEASE_RC7.bat
```

The script uses Git for Windows and Git Credential Manager, pushes the RC7 source to `main`, creates or updates tag `v1.9.0-rc.7`, waits for the multi-platform GitHub Actions workflow, verifies all required assets, and opens the pre-release page.

Expected assets:

- `dicodePing-v1.9.0-rc.7-windows-x64.exe`
- `dicodePing-v1.9.0-rc.7-linux-x86_64.tar.gz`
- `dicodePing-v1.9.0-rc.7-macos-arm64.dmg`
- `dicodePing-v1.9.0-rc.7-macos-x86_64.dmg`
- `dicodePing-v1.9.0-rc.7-android.apk`

Run from source on Windows:

```bat
RUN_SOURCE_RC7.bat
```

Build only the Windows EXE:

```bat
BUILD_RELEASE_RC7.bat
```

Build only the signed Android APK:

```bat
BUILD_SIGNED_APK_RC7.bat
```

Bilingual release notes: `docs/releases/v1.9.0-rc.7.md`.
