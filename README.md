# dicodePing 1.9.0 RC12

RC12 fixes the Telegram scanner transport and progress model across Windows, Linux, macOS and Android.

## Release

Extract the archive and run:

```bat
DEPLOY_PRERELEASE_RC12.bat
```

The deploy script validates the source, pushes it to `main`, creates or updates `v1.9.0-rc.12`, waits for the multi-platform workflow and opens the GitHub pre-release.

Expected assets:

- `dicodePing-v1.9.0-rc.12-windows-x64.exe`
- `dicodePing-v1.9.0-rc.12-linux-x86_64.tar.gz`
- `dicodePing-v1.9.0-rc.12-macos-arm64.dmg`
- `dicodePing-v1.9.0-rc.12-macos-x86_64.dmg`
- `dicodePing-v1.9.0-rc.12-android.apk`

Bilingual release notes: `docs/releases/v1.9.0-rc.12.md`.
