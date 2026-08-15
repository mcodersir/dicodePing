# dicodePing 3

**Release:** `3.0.0-pre.3`

Version 3 is a clean client/runtime architecture. The application keeps the dicodePing subscription ecosystem and product-specific Scanner/business behavior while networking is isolated behind the dedicated dicodePing runtime host. Android follows the same application-layer boundary with a platform-native VPN runtime bridge.

## Release targets

- Windows x64
- Linux x86_64
- macOS arm64
- macOS x86_64
- Android universal APK (`arm64-v8a`, `armeabi-v7a`, `x86_64`)

The repository treats macOS as one product platform with two release architectures.

## Architecture

```text
Modern UI
   │
Application / product service
   ├── Authoritative subscription service
   ├── Scanner / product logic
   └── Profile state
   │
Runtime boundary
   ├── Desktop: dicodePing CoreHost
   │      ├── proxy runtime
   │      ├── routing runtime
   │      ├── system proxy / TUN
   │      └── real latency / statistics / logs
   └── Android: native runtime bridge + VpnService integration
```

The UI never starts or configures proxy cores directly.

## Primary subscription

The built-in primary source is intentionally fixed to the project source:

`https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt`

Optional user sources may be added without replacing the primary source.

## Runtime preparation

`PREPARE_V3_RUNTIME.bat` is the offline verification-and-packaging entry point. It never downloads anything: it verifies the pinned desktop/Android runtime files already present in the checkout and then creates `dist/dicodePing-3.0.0-pre.3-complete.zip`. If any runtime is missing or corrupt, run `REPAIR_V3_RUNTIME.bat` once; the repair helper performs the checksum-pinned downloads and includes Windows curl/DNS-over-HTTPS and Schannel revocation fallbacks.

## Desktop development

Requirements:

- Python 3.12
- .NET SDK 10
- platform packaging tools

```bash
python -m pip install -r requirements-build.txt
python tools/validate_v3.py
python tools/validate_corehost_api_surface.py
python -m pytest -q tests/test_release.py
python app.py
```

Build on the target OS:

```bash
python tools/build_windows.py
python tools/build_linux.py
python tools/build_macos.py
```

## Android

Android requires Java 17+ and an Android SDK. The release helper validates the pinned runtime and produces the universal APK.

```bash
cd dicodePing_android
bash build_apk.sh
```

Release signing variables:

- `ANDROID_KEYSTORE_PATH`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

## Publish `3.0.0-pre.3`

The project root includes `PUBLISH_3.0.0_PRE1.bat` (also mirrored as `RELEASE_V3_PRERELEASE.bat`). It targets **`mcodersir/dicodePing`** directly. No local `GH_TOKEN` is required: clone and push operations use the authentication already configured for `git.exe` (for example Git Credential Manager on Windows, another Git credential helper, or an SSH/insteadOf configuration). The publisher clones the current default branch, replaces it with this Version 3 tree, validates it, commits to the default branch, and creates `v3.0.0-pre.3`. The workflow uses the built-in GitHub Actions token to build every platform and create the GitHub **pre-release** with rebuilt assets.

```bat
PUBLISH_3.0.0_PRE1.bat
```

`gh.exe` is optional. If GitHub CLI is installed and already authenticated, the BAT also waits for the Actions run and verifies the resulting release. If `gh.exe` is missing or not authenticated, publication still proceeds through Git + GitHub Actions. The Android workflow requires the four repository Action secrets documented below.

## Version 3 state

Desktop state is isolated under `dicodePing/v3`. Android state is isolated in the `dicodeping_v3` SharedPreferences store. Both platforms start from a clean Version 3 profile database.

## Licensing

The combined desktop distribution includes GPL-covered components. Required notices and corresponding source references are retained in `THIRD_PARTY_NOTICES.md`, `licenses/`, and `third_party/network-engine/`. Product UI branding does not reproduce upstream UI branding.

## Complete offline package

After the pinned runtime set is present, run `PREPARE_V3_RUNTIME.bat`. It verifies every runtime SHA-256 and invokes the packager as a Python module (`python -m tools.package_complete_v3`) so imports resolve from the repository root on Windows. The generated `dist/dicodePing-3.0.0-pre.3-complete.zip` contains all pinned Xray, sing-box, Wintun and Android runtime files; the archive is re-opened, extracted to a temporary directory, and every runtime digest is verified again before success is reported. `REPAIR_V3_RUNTIME.bat` is only needed if a pinned runtime file is missing or corrupt.
