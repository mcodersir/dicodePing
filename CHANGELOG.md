# Changelog

## 0.1.2 — Windows taskbar icon and release automation

- Added a stable Windows AppUserModelID before Qt creates top-level windows.
- Added a global Qt application icon and a native HWND icon fallback for taskbar and Alt+Tab.
- Embedded multi-resolution icon and version metadata in the PyInstaller executable.
- Consolidated release automation into one GitHub Actions workflow.
- Added reproducible Android core download with SHA-256 verification.
- Added Windows and Android artifacts, SHA256SUMS, SPDX SBOM, and GitHub attestations to tagged releases.
- Added Persian and English documentation plus a GitHub Pages documentation landing page.
- Pinned PySide6 6.11.1 and PyInstaller 6.21.0 for reproducible Windows builds.
- Removed opaque native binaries from the source tree; CI fetches and verifies fixed upstream versions.

## 0.1.1

- Connection, startup, Android UI, routing, Gradle, and stability maintenance release.
