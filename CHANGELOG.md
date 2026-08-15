# Changelog

## 3.0.0-pre.2

- Added selectable automatic, Xray and sing-box core preferences.
- Refined Routing & DNS settings into a compact Linear-style layout.
- Added release-wide runtime, profile, DNS and four-platform validation coverage.

## 3.0.0-pre.1

- Fixed the desktop release builders so Windows, Linux and both macOS jobs can run as direct scripts or Python modules without `ModuleNotFoundError: tools`.
- Updated GitHub Actions runtime actions to Node 24 compatible majors and made release jobs invoke desktop builders with `python -m`.
- Made the pre-release publisher recover safely from an existing `v3.0.0-pre.1` tag and refresh an existing GitHub pre-release instead of aborting.
- Runtime bootstrap now retries GitHub downloads with curl and DNS-over-HTTPS fallbacks, and supports verified offline asset folders.
- Replaced the desktop networking/client implementation with a ServiceLib-based runtime host.
- Preserved the authoritative project subscription source and subscription business rules.
- Rebuilt the desktop interface from scratch around Connection Center, Profiles, Scanner, Routing & DNS, Runtime Logs and About.
- Isolated Version 3 state from earlier installs so stale profile/runtime settings are not imported.
- Single networking architecture across the product, with a dedicated desktop runtime host and Android Xray bridge.
- Added native Hysteria2 handling to the Android Xray adapter.
- Kept a single Android networking path based on the pinned Xray bridge.
- Added release validation for Windows, Linux, macOS arm64/x86_64 and Android universal packages.
- Added pinned runtime staging with integrity checks and third-party license notices.
