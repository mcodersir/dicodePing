# Changelog

## 3.0.0-pre.1

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
