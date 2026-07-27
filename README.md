# dicodePing 1.9.0 RC9

RC9 provides a staged Telegram scanner and multi-platform pre-release workflow.

## One-click GitHub pre-release

On Windows, extract the source ZIP and run:

```bat
DEPLOY_PRERELEASE_RC9.bat
```

The script uses Git for Windows and Git Credential Manager, pushes the RC9 source to `main`, creates or updates tag `v1.9.0-rc.9`, waits for the multi-platform GitHub Actions workflow, validates all expected assets, and opens the pre-release page.

Expected assets:

- `dicodePing-v1.9.0-rc.9-windows-x64.exe`
- `dicodePing-v1.9.0-rc.9-linux-x86_64.tar.gz`
- `dicodePing-v1.9.0-rc.9-macos-arm64.dmg`
- `dicodePing-v1.9.0-rc.9-macos-x86_64.dmg`
- `dicodePing-v1.9.0-rc.9-android.apk`

## Scanner pipeline

1. Start and validate the dicodePing bootstrap VPN.
2. Crawl the bundled DicodeConfigChecker public Telegram channel set.
3. Persist raw candidates before changing the network state.
4. Fully disconnect the bootstrap VPN.
5. Run isolated Xray/HTTP quality probes.
6. Replace the single persistent `SUB` source and refresh the server list.

Default per-channel extraction limits are 8 for rank 1 and 9 for rank 2. The desktop scanner probes a bounded candidate set and saves the fastest verified results.

Bilingual release notes: `docs/releases/v1.9.0-rc.9.md`.

## RC9 Hotfix 2

This source fixes the Android x86_64 bundled-Usque build by using NDK CGO cross-linking. It also serializes native Xray probes, hardens the scanner foreground service and VPN permission lifecycle, and makes automatic connection try up to eight real-verified candidates. The release tag remains `v1.9.0-rc.9` so the recovery workflow can replace the failed partial RC9 assets.
