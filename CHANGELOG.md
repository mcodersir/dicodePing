# Changelog

## 1.6.0-rc.3 — Staged scanner, ETA everywhere, visible quality + volume

### Added
- **Staged scanner rewrite** (`dicodeping/scanner.py`).  The scanner now
  runs as a three-stage pipeline triggered by a single "Start scan"
  button:
  1. **Stage 1 — Connect**: pick the best server from the primary
     source and start a real TUN connection so the crawler can reach
     t.me.
  2. **Stage 2 — Crawl + Probe**: crawl the bundled Telegram channels
     in parallel, then tear down the TUN and real-probe every unique
     config in parallel (48 workers, 3.5s timeout).  The user can press
     "Stop and save" at any point during this stage — whatever servers
     have already been probed and responded are saved immediately.
  3. **Stage 3 — Save**: save the survivors as a new user source whose
     name the user typed before pressing Start.
- **ETA estimator** (`dicodeping/eta.py`).  A sliding-window moving-
  average rate-based time-to-completion estimator.  Used by the splash
  screen, the ping/fetch stages, and the scanner so the user can see
  how long the current operation is expected to take.
- **Visible quality column on Servers page**.  The desktop table now
  has 8 columns (was 7); the new "quality" column shows the bucket word
  (Excellent / Good / Fair / Poor) inline plus the volume label below
  it, with a colour that matches the ping cell.  On Android, a new
  `qualityVolume` badge next to the ping badge shows the same info.
- **Volume-fetch button on Servers page toolbar** (desktop + Android).
  The button was previously only on the scanner page; it now appears on
  the Servers page too and refreshes every server's volume info in
  parallel.
- **Live alive-count badge** on the scanner page that updates as each
  probe completes.
- **Stop button** on the scanner page that lets the user stop the scan
  at any point and save whatever has been found so far.
- **Stage indicator** (three dots) on the scanner page that highlights
  the current stage.
- **Configurable per-channel limits** (rank-1 and rank-2).  Defaults:
  3 per rank-1 channel, 3 per rank-2 channel.

### Changed
- **Auto-server-selection** (`dicodeping/service.py`).  The trusted-ping
  threshold was lowered from 70 ms to 40 ms so faster servers are also
  auto-eligible.  A new `_effective_ping_ms` function weights the raw
  ping by failure history (+80 ms per failure), recent-connection bonus
  (-30 ms if connected in the last hour), and unknown-country penalty
  (+120 ms).  This means a low-ping but flaky server is no longer
  chosen over a slightly higher-ping but reliable one.
- **Scanner probe concurrency** raised from 32 to 48; probe timeout
  lowered from 4.0s to 3.5s; retry budget raised from 4 to 6.
- **Splash screen** now shows an ETA badge under the progress bar.

### Tests
- New `tests/test_v160_rc3.py` with 7 tests covering the ETA module,
  staged scanner, scanner thread signals, new i18n keys, quality column,
  volume button, and stage-dot UI.
- Updated `tests/test_rc4.py` for the new 40 ms auto-ping threshold.
- Updated `tests/test_v160_rc2.py` to accept the rc.2/rc.3 line without
  pinning the exact RC suffix.
- All 106 tests pass.

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
