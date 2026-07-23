# Changelog

## 1.6.0-rc.2 — Scanner rewrite: real Telegram crawler + real volume

### Added
- **Telegram channel crawler** (`dicodeping/crawler.py`,
  `TelegramChannelCrawler.kt`).  Mirrors the "stage 1" logic of
  DicodeConfigChecker: fetches `https://t.me/s/{channel}` for every
  channel in the bundled `assets/channels.txt` (202+ channels), extracts
  vmess/vless/trojan/ss/ssr/hysteria2/tuic configs from the preview HTML,
  and deduplicates them.  Falls back to `telegram.me` when `t.me` is
  unavailable.
- **Scanner rewrite** (`dicodeping/scanner.py`).  The scanner now crawls
  Telegram channels (via the program's own running VPN), real-proxy-probes
  every candidate, drops the unresponsive ones, and stores the survivors
  as a **brand new user source** that appears next to the primary source
  on the Servers page.  The user can optionally type a custom name for
  the new sub; if left blank, an automatic Persian name with the date is
  generated.
- **Real volume detection** (`dicodeping/volume.py`,
  `VolumeDetector.kt`).  The "Fetch volumes" button now issues real HEAD
  requests in parallel for every enabled subscription URL and parses the
  standard `Subscription-Userinfo` HTTP header (used by v2rayN / Nekoray)
  to extract the actual upload/download/total/expire values.  When the
  header is unavailable, the remark-based heuristic is used as a
  fallback.  A 5-minute cache prevents spamming the provider.
- New `SubscriptionClient.fetchUserinfoHeader` in the Android client.
- New `assets/channels.txt` shipped with both desktop and Android
  bundles.

### Changed
- The Scanner page UI is now more minimal: one big primary button, an
  optional name field, a single status line, a slim progress bar, and a
  copy-all button.  No settings exposed.
- After a successful scan, the new source appears immediately on the
  Servers page as a new tab.
- The volume column is exposed on the Servers page tooltip (desktop).

### Tests
- New `tests/test_v160_rc2.py` with 9 tests covering the crawler module,
  scanner rewrite, real volume parsing, VolumeFetchThread source_urls
  passing, custom-name scanner thread, new i18n keys, and minimal UI.
- Updated `test_v160_rc1.py` to assert the 1.6.0 line without pinning
  the exact RC suffix.

## 1.6.0-rc.1 — Scanner, volume detection (beta), quality, bug fixes

### Added
- One-click scanner on Windows, Linux and Android.  A single button bootstraps
  the program's own default subscription, probes every candidate via real-tunnel
  xray probes, drops the unresponsive ones and stores the survivors in a new
  internal subscription with an auto-generated Persian name.  A "Copy all
  servers" button copies the entire subscription (plain text or Base64) to the
  clipboard in one click.  All scanner settings (concurrency, timeouts, retry
  budget, max server count) are hard-coded in `dicodeping/scanner.py` and are
  not exposed in the UI, per the user's request.
- Volume-based config detection (beta).  The remark of each config is parsed
  for traffic or time quotas (`10GB`, `500MB`, `30d`, `1week`, `Volume`).
  A new "Fetch volumes" button refreshes every server's volume info
  simultaneously.  When a volume-limited server is connected, a 1-hour
  auto-disconnect timer is armed automatically.
- Quality detection.  The ping latency is bucketed into Excellent / Good /
  Fair / Poor and the ping cell background is colored accordingly.  The
  bucket label is exposed via the cell tooltip.
- Bundled Vazirmatn font (Regular, Medium, Bold) under `assets/fonts/` and
  registered via `QFontDatabase.addApplicationFont()` so the Persian UI
  renders correctly on Linux distributions that do not ship the font
  system-wide.
- Linux desktop entry (`dicodePing.desktop`) shipped in the bundle.

### Fixed
- Windows crash on Disconnect.  `XrayManager.stop()` is now fully wrapped in
  `try/except` and the PowerShell-driven TUN cleanup runs on a background
  daemon thread, so a failing PowerShell invocation can never crash the GUI.
  The log handle is flushed and closed before unlinking the log file to avoid
  Windows file-lock crashes.
- Linux Vazir font not applied.  The font is now bundled inside the archive
  and registered at startup; no separate Persian font installation is
  required on the user's machine.
- Linux launcher.  `run-dicodePing.sh` now tries `pkexec` → `gksudo` /
  `kdesudo` → `sudo -A` (with `SUDO_ASKPASS`) → `sudo -E` in order and
  prints a friendly bilingual error message if all of them fail.  The README
  has step-by-step instructions in both Persian and English.

### Improved
- Real-tunnel ping probes use a shorter timeout and tunable sample count for
  faster table fill.
- `cleanup_named_tun` logs failures instead of silently swallowing them, so
  future bug reports are easier to triage.
- Quality rating is applied uniformly across desktop and Android.

### Tests
- New `tests/test_v160_rc1.py` covering version bump, scanner module wiring,
  volume + quality modules, i18n keys, defensive Windows disconnect, robust
  Linux launcher and bundled Vazirmatn font.

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
