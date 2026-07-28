# dicodePing 1.9.0 RC13

RC13 fixes the Android Telegram scanner route and keeps the DicodeConfigChecker-style staged scanner on Windows, Linux, macOS and Android.

## Release

Extract the archive and run:

```bat
DEPLOY_PRERELEASE_RC13.bat
```

The deploy script validates the source, pushes it to `main`, creates or updates `v1.9.0-rc.13`, waits for the multi-platform workflow and opens the GitHub pre-release.

Expected assets:

- `dicodePing-v1.9.0-rc.13-windows-x64.exe`
- `dicodePing-v1.9.0-rc.13-linux-x86_64.tar.gz`
- `dicodePing-v1.9.0-rc.13-macos-arm64.dmg`
- `dicodePing-v1.9.0-rc.13-macos-x86_64.dmg`
- `dicodePing-v1.9.0-rc.13-android.apk`

Bilingual release notes: `docs/releases/v1.9.0-rc.13.md`.
