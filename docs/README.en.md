# dicodePing English Documentation

[Project home](../README.md) · [Latest release](https://github.com/mcodersir/dicodePing/releases/latest) · [Architecture](ARCHITECTURE.md) · [Security](../SECURITY.md) · [Persian documentation](README.fa.md)

## Overview

dicodePing is an open-source Windows and Android client that imports, evaluates, ranks, and runs Xray-based connection profiles. A reachable host or open TCP port is treated only as a pre-check. Final eligibility requires a successful request through the actual proxy path.

## Current release

Version `0.1.2` contains a complete Windows shell-icon fix. The icon is applied through:

1. a multi-resolution icon resource embedded in the executable;
2. the global `QApplication` icon before top-level windows are created;
3. a stable Windows `AppUserModelID` for shell grouping;
4. native small and large HWND icons for the taskbar and Alt+Tab.

## Install on Windows

1. Open the [latest GitHub Release](https://github.com/mcodersir/dicodePing/releases/latest).
2. Download `dicodePing-v0.1.2-windows.exe`.
3. Verify its digest against `SHA256SUMS`.
4. Start it with the requested Administrator permission so it can create the TUN interface.

## Install on Android

The release publishes two APK variants:

- `android-debug-signed.apk` is installable and intended for direct testing/use.
- `android-release-unsigned.apk` is the release build without a private production signing key. Sign it with the project owner's keystore before store distribution.

Android 7.0 or newer is required. Android displays the standard `VpnService` consent dialog on first connection.

## Connection-quality model

The evaluator performs:

1. profile and endpoint validation;
2. a bounded TCP pre-check;
3. startup of the actual Xray/SOCKS path;
4. an HTTP/HTTPS health request through that path;
5. median latency and jitter scoring;
6. exclusion of failed profiles from automatic selection.

The result is closer to real user-perceived connectivity than ICMP-only ranking.

## Privacy

- Settings and caches are stored locally.
- No mandatory account or first-party telemetry is included.
- Imported subscriptions may contain credentials; never post them in public issues or logs.
- See [PRIVACY.md](../PRIVACY.md).

## Build from source

### Windows

```powershell
py -m pip install -r requirements-build.txt
py tools/verify_version.py
py -m unittest discover -s tests -v
py tools/quality_gate.py
py tools/build_windows.py
```

### Android

```bash
cd dicodePing_android
chmod +x gradlew
./gradlew --no-daemon lint test assembleDebug assembleRelease
```

The pinned Android core AAR must be installed at the path documented by the Android subproject. The official CI workflow downloads the upstream asset and verifies its fixed SHA-256 digest before building.

## Release integrity

Tagged releases are built by GitHub Actions and publish:

- SHA-256 checksums;
- an SPDX SBOM;
- GitHub artifact attestations backed by OIDC/Sigstore;
- the source commit and release tag.

See [TEST_MATRIX.md](TEST_MATRIX.md) for real-device validation scenarios.
