# Changelog

## 3.0.0-pre.6

- Desktop connection state is now gated by a real HTTP request through the newly started local SOCKS proxy, before TUN/system-proxy state is published on Windows, Linux, and macOS.
- Increased bounded desktop real-ping capacity to 24 concurrent workers and aligned the client RPC estimate with that runtime limit.
- Android normal TCP checks now retain their one-second timeout while scanner filtering stays fast; bounded real-proxy concurrency increased to 12 workers on capable devices.
- Updated the connection UI to show the verified real-traffic latency immediately after a successful desktop connection.

## 3.0.0-pre.5

- Real Ping now uses bounded concurrent workers for Xray and sing-box on Windows, Linux and macOS, plus native Android probes.
- Removed the silent 80-profile limit; every requested profile is tested and receives a real result or an explicit failure.
- Scanner TCP filtering and real Xray checks now run in separate bounded parallel phases.
- Clarified the desktop and Android UI so users can see that the test is real, parallel and proxy-backed.
- Updated release validation, packaging metadata and workflow assets for `v3.0.0-pre.5`.

## 3.0.0-pre.4

- Parallel server ping tests with live low-to-high sorting.
- Connect or select a server while the ping sweep is still running.
- Rebuilt the Android server screen with rounded cards, clearer spacing and a faster progress model.

## 3.0.0-pre.3

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
