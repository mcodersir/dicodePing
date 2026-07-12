# Validation report — dicodePing v0.1.2

Validation date: **2026-07-12**

## Reproducible source checks

| Check | Result |
|---|---|
| Desktop/Android/tag version parity | Passed (`0.1.2`, Android `versionCode 3`, tag `v0.1.2`) |
| Python bytecode compilation | Passed |
| Unit and maintenance tests | **27 passed** |
| Security/quality gate | Passed with no errors or warnings |
| Android project validator | Passed; **52** XML/manifest files parsed and **125** Persian/English localized resources matched |
| GitHub Actions YAML parse | Passed for every root workflow |
| SPDX SBOM generation and JSON parse | Passed; 20 packages and 19 dependency relationships |
| Private-key/signing-material scan | Passed; no signing key is tracked |
| Opaque native-artifact policy | Passed; Xray, Wintun, Geo assets, and Android AAR are not tracked in source |

## Windows icon fix

The Windows shell icon is now applied at every relevant layer:

1. a multi-resolution ICO containing 16, 24, 32, 48, 64, 128, and 256 pixel entries;
2. the PyInstaller executable icon and Windows version resource;
3. a global `QApplication` icon before any top-level window is created;
4. a stable `AppUserModelID` before `QApplication` starts;
5. native `WM_SETICON` small and large icons after the HWND is created.

Static regression tests verify the initialization order, executable metadata, ICO resolutions, and Win32 integration path.

## Connection and routing checks

- Server selection excludes failed profiles and scores successful real-proxy probes by median latency plus jitter penalty.
- TLS certificate verification remains enabled.
- Android routes both `0.0.0.0/0` and `::/0` through `VpnService`; IPv6 therefore fails closed rather than bypassing the tunnel.
- Private/link-local IPv4 and IPv6 ranges are represented explicitly in direct-routing policy.
- Network, process, parsing, and hashing work are kept off the main UI thread by the existing worker/coroutine architecture.

## Reproducible supply chain

- Windows uses Xray-core `26.7.11` and Wintun `0.14.1` from pinned upstream locations.
- The Xray archive is checked against its upstream companion SHA-256 digest before extraction.
- The Wintun archive is checked against a fixed SHA-256 value.
- Android uses AndroidLibXrayLite `26.6.2`; CI verifies the fixed AAR SHA-256 before Gradle starts.
- Releases publish `SHA256SUMS`, an SPDX 2.3 SBOM, third-party notices, license texts, and GitHub artifact attestations.

## Environment boundary

The final Windows GUI/EXE was not executed in this Linux workspace, and this workspace has no Android SDK/device matrix. The tagged GitHub Actions workflow is therefore the authoritative binary build path: Windows is built on `windows-latest`; Android lint, tests, and APK assembly run on `ubuntu-latest` with the pinned core.

Real-device acceptance remains defined in [`docs/TEST_MATRIX.md`](docs/TEST_MATRIX.md), including Windows 10/11, multiple Android API levels, IPv4/IPv6/DNS leak checks, network handover, sleep/restart, permission revoke, and service cleanup.
