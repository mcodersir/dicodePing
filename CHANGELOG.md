# Changelog

## 1.9.0 RC6

- Integrated DicodeConfigChecker-style real Xray HTTP verification with repeated samples and median latency.
- Added complete splash-screen source refresh, testing, geolocation and update checks before the UI opens.
- Split scanner logs into All, Telegram and Real tests views with independent live metrics.
- Corrected Persian right-edge and English left-edge sidebar alignment.
- Added Android repeated native-core scanner verification and the single atomic `SUB` lifecycle.
- Added bilingual Persian/English release notes and RC6 multi-platform pre-release automation.

## 1.9.0 RC5 Android build hotfix

- Fixed the Gradle Kotlin DSL `Illegal escape: \.` error in the native-library validation regex.
- Added local, test-suite, and GitHub Actions preflight checks so this exact script-compilation regression is rejected before the APK build.

## 1.9.0 RC5

- Replaced the scanner's fixed 20-second bootstrap poll with a worker-result handshake and separate 55-second connection / 18-second teardown guards.
- Made scanner progress, throughput metrics and highlighted logs responsive; removed ETA output.
- Scanner persistence now atomically replaces exactly one local source named `SUB`, immediately populates Servers, and cascades deletion from Settings > Sources.
- Moved desktop disconnect to an asynchronous worker and retained Qt threads until `finished`, preventing Windows/Linux/macOS teardown crashes.
- Removed duplicate blocking `manager.stop()` from the failed-connect GUI path.
- Aligned sidebar icons and labels to the outer edge in RTL/LTR layouts with a minimal selected state.
- Updated Android to API 36, AGP 8.10.1 and Gradle 8.11.1; release packages only 64-bit ABIs and uses modern JNI packaging.
- Serialized Android native-core lifecycle calls and removed the common-source tethering-controller collision.
- Added signed-APK 16 KiB zip-alignment and ABI checks to the release workflow.
- Added one-click RC5 Git deployment and existing-pre-release recovery.

## 1.9.0 RC4 Existing Release Recovery Hotfix 7

- Existing or partial `v1.9.0-rc.4` releases no longer abort the one-click deploy.
- Added a dedicated main-branch release trigger so recovery does not depend on a second tag-created event.
- The workflow now updates an existing release and overwrites same-name assets after all platform jobs succeed.
- The deploy script force-moves the RC4 tag to the fixed commit when allowed and falls back cleanly when tag protection blocks it.
- Release waiting is bound to the exact pushed commit instead of returning success merely because an old release page exists.
- Final verification requires Windows EXE, Android APK, Linux archive, and both macOS DMGs.

## 1.9.0 RC4 Android release recovery hotfix

- Removed the stale `app/src/main/.../AndroidTetheringController.kt` implementation that collided with the `standard` product-flavor implementation.
- Added Android project validation and CI guards so the Kotlin redeclaration cannot return silently.
- Updated the one-click deploy script to recover a failed RC4 tag run when no GitHub Release was created.
- Removed the obsolete `android:extractNativeLibs` manifest attribute; native packaging remains configured by Gradle.

## 1.9.0 RC4 Git Deploy Hotfix 5

- Replaced GitHub CLI token validation with native Git HTTPS authentication.
- Added Git Credential Manager browser login fallback for Windows.
- Deployment now pushes `main` and the `v1.9.0-rc.4` tag using Git.
- The release workflow starts automatically from the tag push.
- Added local release polling and early GitHub Actions failure detection.

# Changelog

## 1.9.0 RC4 Legacy Release Hotfix 2

- Restored the v1.8.0-rc.4 release layout: one-file Windows EXE, portable Linux tar.gz and signed Android APK.
- Added macOS DMG artifacts for Apple Silicon and Intel runners.
- Kept desktop signing optional and limited mandatory owner signing to the Android release APK.
- Restored SHA-256-pinned Aether and WARP/Usque core archives as separate GitHub Release assets for Windows, Linux and macOS.
- Pinned all CI desktop builds to Python 3.12 and kept packaged smoke tests for Windows and Linux.

## 1.9.0 RC3

- Reworked the Telegram scanner around bounded adaptive concurrency to prevent UI stalls and process storms.
- Added highlighted structured scanner logs with capped history and batched GUI delivery.
- Replaced unreliable ETA output with live Telegram throughput, channel rate, config count, probe rate, and healthy count.
- Added direct SOCKS5 crawling through Aether/WARP while keeping Xray TUN crawling on direct sockets.
- Fixed duplicate scanner log retention, leaked watcher threads, repeated reconnect of an already-active bootstrap connection, and unsafe cross-thread UI/connection calls.
- Added cooperative cancellation, bounded retries, early stop after five healthy servers, and clean application shutdown.
- Added RC3 Windows build/run entrypoints and focused scanner regression tests.

## 1.9.0 RC2

- Fixed the Xray `core_options` startup crash.
- Corrected Aether 1.4.0 CLI flags and removed unsupported `--perf` / `--wireguard` arguments.
- Added MASQUE-only HTTP/2 fallback and faster Balanced defaults.
- Made WARP registration non-interactive, atomic, validated, and bounded by timeout.
- Added background core activation, visible progress, persistent core/profile settings, and a durable Aether identity/last-route config.
- Added a one-click Windows RC2 release builder and regression tests.

## 1.9.0 RC1

- Added the first macOS Apple Silicon release artifact.
- Bundled SHA-256 verified Aether 1.4.0 and Usque 4.2.1 with Desktop builds.
- Added independent Aether/WARP protocol, scan, transport, performance and
  quick-reconnect controls.
- Added Xray-backed DNS-over-HTTPS to Desktop and Android.
- Documented AGPL/MIT/MPL/LGPL obligations and non-copied GUI references.
- Kept unsupported Android CLI-only transports explicitly disabled instead of
  reporting fake availability.

## 1.8.0-rc.4 — honest latency, reliable connect, live locale, core-first Home

- Server rows now preserve and display two separate measurements: endpoint
  ICMP RTT and verified HTTP latency through the exact Xray configuration.
  Health and automatic selection continue to require the Xray HTTP probe.
- Selected-server refresh no longer promotes a TCP-only result to healthy.
- Xray startup now validates the selected outbound through a private SOCKS
  inbound before validating system-wide TUN routing, waits for bounded
  Windows/Linux route propagation, and routes the Stats API correctly.
- Xray validation/API ports use the central registry and are released on every
  stop/error path.
- English navigation is fixed to the left and Persian navigation to the right.
  Changing language rebuilds the presentation tree immediately without a
  process restart or losing the active connection manager.
- Activating Aether or WARP changes Home into a dedicated core control screen
  with an explicit Connect/Disconnect action; server/scanner content is hidden.
- Aether uses Ironclad correctly and both Aether and Usque automatically retry
  filtered QUIC/MASQUE startup over HTTP/2.
- Alternative-core monitoring accepts explicit unsupported traffic counters
  without crashing, and teardown still waits for every owned process.
- Python package `1.8.0rc4`, Android `versionName 1.8.0-rc.4` and
  `versionCode 35`.

## 1.8.0-rc.3 — strict lifecycle, verified scanner, honest capabilities

- Added a serialized core lifecycle with generation cancellation, central
  process/port registries, bounded termination and application-exit disposal.
- Added verified on-demand Aether 1.4.0 and Usque 4.2.1 desktop installers with
  redirect, size, archive-bomb, staging, self-test and rollback controls.
- Rebuilt Scanner bootstrap selection around real Xray HTTP probes and removed
  every continue-on-TUN/disconnect-error path.
- Added bounded concurrent Xray probing, live ETA/alive signals, Stop with
  partial save and cross-file transactional persistence.
- Added one canonical ranked channel manifest shared by desktop and Android;
  removed Telegram proxy and volume paths from Scanner.
- Moved Android scanning to an application-owned coordinator and foreground
  service with Stop notification and no automatic reconnect.
- Scanner now stops new probes after five HTTP-verified healthy results and
  keeps the fastest five, reducing mobile scan time and resource use.
- Server rows show conservative quota, Cloudflare Worker, or persistent hints
  only when explicit config metadata supports the label.
- Updated AndroidLibXrayLite to 26.7.11.
- Disabled Android Aether, Psiphon and WARP honestly; no external APK, Termux,
  or raw executable is downloaded.

## 1.8.0-rc.2 — responsive UI, Persian-first migration, adaptive Android

- Added centralized design tokens and deterministic desktop/Android size classes.
- Replaced overflowing Settings tabs with adaptive category navigation.
- Added compact server cards and fixed the Pin/Action column regression.
- Rebuilt the Scanner stepper and removed its ambiguous date placeholder.
- Added System/Light/Dark themes, reduced motion and Persian-first migration.
- Added Android medium Scanner navigation and expanded navigation rail.
- Preserved connection, discovery, probe and Xray backend contracts.

## 1.8.0-rc.1 — verified optional cores, real sharing, named scanner sources

- Added one-active-core runtime selection for Xray, Psiphon and Aether.
- Added verified, on-demand optional-core downloads outside application builds.
- Added Aether Ironclad real-tunnel validation and quick reconnect.
- Implemented Windows ICS and Linux hostapd/dnsmasq/iptables VPN sharing.
- Wired Android per-app VPN allowlist and denylist controls to VpnService.
- Added Android root/system tether routing with explicit capability failure.
- Added working CDN endpoint formatting to desktop and Android Xray configs.
- Preserved custom scanner subscription names and persisted real scanned sources.
- Added atomic installs, lifecycle cleanup, rollback, resource scaling, and tests.

## 1.7.0-rc.4 — adaptive core, stable lifecycle, real scanner, responsive UI

### Fixed
- Android scanner results are now imported into the repository, resolved,
  verified with the embedded Xray core, persisted, and selected automatically.
- Desktop scanner cancellation now reaches active Xray probe processes. The
  per-scan forever-waiting thread was removed and pending work is bounded.
- Repeated connect/disconnect no longer creates overlapping Android core starts
  or unlimited desktop TUN cleanup threads.
- Connected latency on desktop is a real HTTP round trip through the TUN,
  instead of a direct TCP handshake to the proxy endpoint.
- Automatic desktop connection retries up to five independently ranked servers
  and records failed candidates before presenting an error.

### Added
- CPU/RAM-aware resource profiles for Windows, Linux, and Android tune crawler,
  DNS, ping, native-probe concurrency, internal queues, and Xray `bufferSize`.
- Regression tests for low-resource limits, queue caps, Xray policy generation,
  and cancellation before process launch.

### UI
- Desktop layouts now reflow actions, toolbars, scanner controls, metrics, and
  tables at narrow widths; the minimum supported window is 680×480.
- Android home header now shows «رفع تحریم‌ها» on the right and the boxed
  `dicodeping` brand on the left in Persian layout.

## 1.7.0-rc.3 — ICMP ping fix, scanner VPN disconnect fix, crash fix, UI improvements

### Fixed
- **ICMP ping** (`dicodeping/icmp_ping.py`).  Simplified to send a
  single ICMP Echo Request with a short timeout.  The previous version
  tried multiple attempts and took too long, causing pings to appear
  as >1000ms on Windows and Linux.
- **Scanner VPN disconnect** (`dicodeping/scanner.py`).  The scanner
  now disconnects the bootstrap VPN AFTER crawling but BEFORE probing,
  exactly as DicodeConfigChecker does.  Previously the VPN was
  disconnected after probing, which meant the probes were testing the
  bootstrap VPN server, not the crawled configs.
- **Disconnect crash** (`dicodeping/xray.py`).  The `stop()` method
  is now completely bulletproof — no exception can propagate to the
  GUI thread.
- **Connection status**.  When connected, the sidebar now shows
  "Connected" instead of "Processing".

### Changed
- **Scanner sub name** is always "sub".  Each scan updates the same
  "sub" source — no need for the user to pick a name.
- **Stop button** is available from the start of the scan and is
  always enabled.
- **Quality column** is hidden by default on Windows/Linux.  Can be
  toggled from Settings.
- **Scanner log** uses ✓ for success and ✗ for failure with
  color-coded highlighting.

### Tests
- All 114 existing tests pass.

## 1.7.0-rc.2 — ICMP ping fix, quality improvement, real per-app VPN, real VPN sharing

### Fixed
- **ICMP ping** (`dicodeping/icmp_ping.py`, `dicodeping/net.py`).  The
  ping now uses the system ``ping`` command (which sends real ICMP Echo
  Request packets) as the primary method.  This works without root on
  Linux and without any special privileges on Windows.  Falls back to
  the Windows IcmpSendEcho API or raw sockets when ``ping`` is not
  available.  The previous implementation silently failed on Linux
  when raw sockets were not available.
- **Quality detection** (`dicodeping/volume.py::rate_quality`).  The
  algorithm now accounts for jitter (from ICMP sample standard
  deviation) and failure history, not just ping latency.  New
  thresholds: Excellent ≤ 150ms/20ms jitter/0 failures; Good ≤ 350ms/
  50ms/2 failures; Fair ≤ 800ms/100ms/5 failures; Poor otherwise.

### Added
- **Real per-app VPN** (Android `DicodeVpnService.kt`).  Uses
  `addAllowedApplication` for allowlist mode and
  `addDisallowedApplication` for denylist mode.  Three modes: disabled
  (default), allowlist (only selected apps use VPN), denylist (selected
  apps bypass VPN).  Settings stored in `SettingsStore.kt` and passed
  to the VPN service via intent extras.
- **Real VPN sharing** (`dicodeping/vpn_sharing.py`).  Windows uses
  `netsh routing ip nat` to enable NAT on the TUN interface.  Linux
  uses `iptables` MASQUERADE and FORWARD rules plus IP forwarding.
  Toggled from Settings; sharing rules are installed when a VPN
  connection starts and removed when it stops.
- **Android settings** for per-app VPN mode, per-app packages, VPN
  sharing USB, VPN sharing hotspot, CDN formatting enabled, and CDN
  formatting domain in `SettingsStore.kt`.

### Tests
- All 114 existing tests pass.

## 1.7.0-rc.1 — Scanner rewrite, volume removal, alternative cores, VPN sharing

### Added
- **Scanner fully automatic with live log** (`dicodeping/scanner.py`).
  The scanner now actually connects a VPN, crawls Telegram channels,
  disconnects the VPN, probes each config, and saves the survivors —
  all from a single button.  A live log panel shows every event in
  real time.  The scanner polls `is_connected_callback` to wait for
  the TUN to actually come up before crawling.
- **Core download manager** (`dicodeping/core_manager.py`).
  Alternative cores (Psiphon, Aether) are not bundled with the build.
  The user downloads them from inside the app on first use.  Each core
  has a URL, SHA-256 digest, and automatic archive extraction.  Only
  one core can be active at a time.
- **Connection method selection** (`dicodeping/conn_methods.py`).
  Three methods: Xray (default), Psiphon, Aether (Ironclad).  When a
  non-default method is active, the Servers page is disabled.
- **CDN formatting** (`dicodeping/conn_methods.apply_cdn_formatting`).
  Rewrites vmess/vless/trojan config URIs to use a CDN fronting domain
  while preserving the original host as SNI/Host.
- **VPN sharing settings** (desktop + Android).  Toggle for USB tether
  and hotspot sharing.
- **Per-app VPN settings** (Android).  Allow only selected apps to use
  the VPN, or deny selected apps from using the VPN.
- **Live scanner log panel** in the desktop UI.
- **Stage preview** shown before the Start button.
- New i18n keys for all new features in both fa and en.

### Removed
- **Volume detection feature** completely removed per user request.
  The `volume.py` module now only contains the `rate_quality` helper
  and a no-op `VolumeAutoDisconnect` stub for backward compat.  All
  volume-related UI elements (fetch button, volume column, volume
  label) have been removed from both desktop and Android.

### Changed
- Version bumped to 1.7.0.
- Android versionCode 28.
- Scanner now emits `log_line` signal for every event.
- Scanner now accepts `is_connected_callback` to poll TUN readiness.
- `ScannerThread` now has `log_line` and `is_connected_callback` params.
- `CoreDownloadThread` added to workers.py for background core downloads.
- Settings page has two new tabs: "Connection methods" and "VPN sharing".

### Tests
- All 114 existing tests pass.
- Test files updated to accept the 1.7.0 version line.

## 1.6.0-rc.4 — Fully-automatic scanner, icon-only volume, source-scoped actions, 20-min cache

### Added
- **Fully-automatic scanner** (`dicodeping/scanner.py`, `dicodeping/ui.py`,
  Android `ScannerFragment.kt` + `fragment_scanner.xml`).  The scanner now
  does everything from a single "Start scan" button — no manual pre-connect
  required.  A stage-preview card is shown above the button so the user
  knows exactly what will happen:
    1. Auto-connect to the best primary-source server
    2. Fetch configs from Telegram channels
    3. Disconnect and test servers in parallel
    4. Save healthy servers as a new subscription
  A hint in blue reads "Just press Start scan once. The rest is automatic!".
- **20-minute ping/location cache** (`dicodeping/ping_cache.py`).  Persists
  the most recent ping and location for each server for 20 minutes so the
  splash screen can reuse them on the next launch.  Only genuinely new or
  stale servers are re-probed, which makes the splash path much faster.
  Cache lives in ``DATA_DIR/ping_cache.json`` and survives restarts.
- **`refresh_saved_with_cache`** in `service.py` — the cache-aware variant
  of `refresh_saved` that splits records into `(cached, fresh)` and only
  re-probes the fresh subset.
- **`refresh_subset`** in `service.py` — re-pings only the servers whose
  IDs are in a given set.  Used by the source-scoped refresh action.
- **`RefreshSubsetThread`** in `workers.py` — the worker that calls
  `refresh_subset` from the UI thread.
- **Stage-preview i18n keys** (`scanner_preview_title`,
  `scanner_preview_1..4`, `scanner_preview_hint`) in both fa and en.

### Changed
- **Volume-fetch button is now icon-only** on the Servers page (44dp wide,
  no text).  This keeps the toolbar responsive when the system font is
  large.  The scanner page button still has text.
- **Volume fetch now falls back to a ranged GET** when HEAD is rejected.
  Many subscription providers only honour GET, so the previous HEAD-only
  path could never extract the real `Subscription-Userinfo` header for
  them.  The new `_try` helper tries HEAD first, then `GET` with
  `Range: bytes=0-0`.
- **Source-scoped ping/volume** (`dicodeping/ui.py`,
  `ServersFragment.kt`).  When the user has a specific source tab active
  (not "all"), the ping and volume-fetch buttons now only operate on that
  source's servers — much faster than re-pinging the whole list.
- **Android `AppRepository.pingSource(sourceId)`** — re-pings only the
  servers whose `sourceId` matches.  Wired into `ServersFragment` so the
  refresh and pingAll buttons are source-scoped when a chip is active.

### Tests
- New `tests/test_v160_rc4.py` with 10 tests covering the ping cache
  module, `refresh_saved_with_cache` + `refresh_subset` in service,
  `RefreshSubsetThread` in workers, source-scoped UI actions, icon-only
  volume button, scanner preview stages, HEAD→GET fallback, and Android
  source-scoped actions.
- All 116 tests pass.

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

### RC4 Auto Deploy Hotfix 3
- Added `DEPLOY_PRERELEASE_RC4.bat` for one-click GitHub authentication, Android secret setup, clean staging, commit/push, workflow dispatch, run monitoring and pre-release opening.
- Changed the RC4 release workflow to `workflow_dispatch` only to prevent duplicate builds after source pushes.

- Hotfix 4: deployment BAT now supports ephemeral classic-token authentication through a hidden prompt, validates repo access, configures Git HTTPS through GitHub CLI, and clears token variables on exit.
