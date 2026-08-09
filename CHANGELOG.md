## 2.0.6 stable

- Fixed the CodeQL security result by removing the unverified `ssl.CERT_NONE` SOCKS HTTPS probe; Xray liveness fallbacks now validate certificate chains and hostnames with the packaged CA bundle.
- Failed GitHub checks now include their own title, summary, details, and annotations in `RELEASE_ERROR_v2.0.6.txt`, instead of only a generic link.
- Fixed CodeQL Android resource linking by materializing the integrity-verified Vazirmatn Regular, Medium, and Bold TTF resources before Gradle runs; the font family is no longer allowed to reference missing files.
- Fixed headless Linux CI by deferring PySide6 QtGui/EGL imports until UI patch installation.
- Fixed CodeQL Android compilation so it does not require runtime Aether/Usque binaries, while real APK and release builds still build and verify all native helpers.
- Added exact-SHA CI/CodeQL tracking, transient merge retry with state verification, failed-step log reporting, resumable release dispatch, and post-publication asset/commit verification.
- The publisher opens the GitHub Release page only after the release is stable, Latest, commit-matched, and complete.
- Preserved Git file modes during manifest staging.

## 2.0.6 stable connectivity and concurrent ping/geo

- Fixed the stable Windows publisher to stage only checksum-manifest files, preventing stale tests and old release helpers from dirty extracted folders from entering validation or commits.
- Made Apple captive-portal detection the primary real connectivity probe with independent fallbacks.
- Parallelized normal ping and geo enrichment on desktop and Android while sharing DNS results.
- Added fast TCP prefiltering before expensive Xray probes and bounded process concurrency.
- Fixed verified CA discovery in packaged macOS builds with bundled certifi data.
- Prevented Android application/core traffic from looping into its own VPN.
- Added robust cleanup and validation for obsolete downloadable-font certificate resources.
- Published stable four-platform artifacts with versionCode 62 and universal Android ABIs.

## 2.0.5 stable universal Android APK (armeabi-v7a support)

- Fixed Android APK showing as "incompatible" on 32-bit ARM devices (armeabi-v7a). Previously only arm64-v8a and x86_64 were packaged; now the APK is universal and includes armeabi-v7a too.
- Updated `build.gradle.kts` `abiFilters` in both `standard` and `rooted` flavors to `setOf("arm64-v8a", "armeabi-v7a", "x86_64")`. Added `armeabi-v7a` ELF machine code (40) to the `expectedMachines` map.
- Updated `prepare_bundled_cores.py` to build Aether (Rust) and Usque (Go) for armeabi-v7a: added `armv7-linux-androideabi` cargo target and `GOARCH=arm` with `armv7a-linux-androideabi` clang prefix.
- Updated `release.yml` to install the `armv7-linux-androideabi` Rust target and to verify all three ABIs (`arm64-v8a armeabi-v7a x86_64`) in the final APK. Only `x86` (32-bit Intel) remains rejected since it is not built.
- Updated `verify_apk_cores.py` `ABIS` map to include `armeabi-v7a: 40`.
- Updated `validate_project.py` ABI check to accept the new three-ABI set.
- Added v2.0.5 validator and test checks for the universal ABI configuration.
- APK size grows ~10-15 MiB because native libraries (libgojni, libaether, libusque) are now packaged for three ABIs instead of two. This is the natural trade-off for universal device support.
- Bumped version: `RELEASE_VERSION = "2.0.5"`, `versionCode = 61`, `versionName = "2.0.5"`, `APP_VERSION = "2.0.5"` in all three desktop builders, Windows version-info tuple `(2, 0, 5, 0)`, `VERSION` in `build_apk.sh` and `build_apk.bat`.
- Renamed `tools/validate_v204_stable.py` → `tools/validate_v205_stable.py` and `tests/test_v204_stable*.py` → `tests/test_v205_stable*.py`.
- Updated `release.yml`, `DEPLOY_RELEASE_200.bat`, `docs/site/index.html`, `docs/releases/v2.0.5.md`, `dicodePing_android/tools/validate_project.py` to reference v2.0.5 / versionCode 61.

## 2.0.4 stable blob_to_config fix + dark theme + splash fallback + save overlay

- Fixed desktop `NameError: name 'blob_to_config' is not defined` in `enrich_saved_scanner_records` (scanner.py). The function was added in v2.0.1 but `blob_to_config` was only imported locally inside another function. Now imported at module level.
- Fixed Android dark theme brown background: the Material3 theme was leaking default warm/purplish surface colors (`colorSurfaceVariant`, `colorSurfaceContainerLow`, etc.) which look brown. Added explicit overrides for ALL Material3 surface roles (`m3_surface_variant`, `m3_surface_lowest`, `m3_surface_low`, `m3_surface_high`, `m3_surface_highest`, `m3_outline_variant`, `m3_error`, `m3_inverse_surface`, etc.) in `values-night/colors.xml`, `values/colors.xml`, and wired them all into `themes.xml` plus `android:colorBackground`.
- Fixed Android first-launch splash: `refreshServersInternal()` now tries three URLs in order for the default source (`raw.githubusercontent.com`, `cdn.jsdelivr.net`, `fastly.jsdelivr.net`) so the splash can download the subscription even when GitHub raw is blocked.
- Added Telegram-style blocking loading overlay during Stop+Save on all platforms. Android: `scannerSaveOverlay` FrameLayout in `fragment_scanner.xml` with a semi-transparent background + centered indeterminate ProgressBar, shown when stage is SAVING or stopRequested+PROBING/DISCONNECTING, hidden when stage reaches STOPPED/DONE, then the enrichment modal appears. Desktop: `_show_scanner_save_overlay()` / `_hide_scanner_save_overlay()` in `ui.py` using a semi-transparent QWidget with an indeterminate QProgressBar, shown in `stop_scanner()` and hidden in `_scanner_thread_finished()`.
- Further scanner speed improvements: `SCANNER_TCP_PROBE_CONCURRENCY` 16→20, `SCANNER_TCP_PROBE_TIMEOUT_MS` 800→600ms, `SCANNER_NATIVE_CANDIDATE_LIMIT` 48→32, `SCANNER_HEALTHY_TARGET` 48→32, `SCANNER_TEST_ATTEMPTS` 2→1, `SCANNER_ATTEMPT_GAP_MS` 40→0. Net effect: 40-candidate scan now takes 6-10s (vs 10-15s in v2.0.3).
- Bumped version: `RELEASE_VERSION = "2.0.4"`, `versionCode = 60`, `versionName = "2.0.4"`, `APP_VERSION = "2.0.4"` in all three desktop builders, Windows version-info tuple `(2, 0, 4, 0)`, `VERSION` in `build_apk.sh` and `build_apk.bat`.
- Renamed `tools/validate_v203_stable.py` → `tools/validate_v204_stable.py` and `tests/test_v203_stable*.py` → `tests/test_v204_stable*.py`; added checks for blob_to_config import, dark theme overrides, fallback URLs, save overlay.
- Updated `release.yml`, `DEPLOY_RELEASE_200.bat`, `docs/site/index.html`, `docs/releases/v2.0.4.md`, `dicodePing_android/tools/validate_project.py` to reference v2.0.4 / versionCode 60.

## 2.0.3 stable first-launch splash + faster scanner

- Fixed first-launch splash on Android: `AppRepository.initialize()` now resolves IP+location for the 30% startup sample inline (before openMain) instead of deferring to `finishStartupInBackground()` which only ran after openMain and was capped at 48 rows. First-launch users now see flags and pings immediately.
- Added an explicit `firstRun` flag in `AppRepository.initialize()` and `SplashActivity` so a first launch always triggers a full source download even when cached data somehow exists.
- Added `FIRST_RUN_STARTUP_TIMEOUT_MS = 75_000ms` in `SplashActivity` (vs 38s for cached launches) so the first-launch pipeline (download + 30% ping + inline geo) has enough time to complete.
- Added `splash_resolving_locations` string to `values/strings.xml` and `values-fa/strings.xml`, and surfaced the `geo` stage in `SplashActivity.renderProgress` so the splash shows "در حال یافتن موقعیت سرورها…" while geo resolves.
- Fixed desktop cached-splash path: `app.py` called `service.refresh_sampled(ratio=0.30, ...)` which did not exist, silently falling through to the except block. Implemented `ServerService.refresh_sampled(ratio, ...)` in `dicodeping/service.py`: deterministic 30% per source, parallel ICMP/TCP ping, parallel geo, sort, persist. Cached-splash users now get a fresh sample ping + location refresh at startup.
- Sped up Android scanner Phase A: `SCANNER_TCP_PROBE_CONCURRENCY` raised from 12 to 16, `SCANNER_TCP_PROBE_TIMEOUT_MS` lowered from 1400ms to 800ms. Dead hosts are filtered out faster and Phase B starts sooner.
- Sped up Android scanner Phase B: `SCANNER_NATIVE_CANDIDATE_LIMIT` lowered from 96 to 48. Only the top 48 candidates (by TCP delay) are Xray-probed, which is enough to reach `SCANNER_HEALTHY_TARGET = 48` and cuts Phase B time in half.
- Net effect on a typical 40-candidate scan: Phase A 1-2s, Phase B 8-12s, total 10-15s (vs 15-20s in v2.0.2 and 60-90s in v2.0.0/2.0.1).
- Bumped version: `RELEASE_VERSION = "2.0.3"`, `versionCode = 59`, `versionName = "2.0.3"`, `APP_VERSION = "2.0.3"` in all three desktop builders, Windows version-info tuple `(2, 0, 3, 0)`, `VERSION` in `build_apk.sh` and `build_apk.bat`.
- Renamed `tools/validate_v202_stable.py` → `tools/validate_v203_stable.py` and `tests/test_v202_stable*.py` → `tests/test_v203_stable*.py`; added checks for first-launch splash, refresh_sampled, SCANNER_TCP_PROBE_TIMEOUT_MS = 800, SCANNER_NATIVE_CANDIDATE_LIMIT = 48, splash_resolving_locations strings.
- Updated `release.yml`, `DEPLOY_RELEASE_200.bat`, `docs/site/index.html`, `docs/releases/v2.0.3.md`, `dicodePing_android/tools/validate_project.py` to reference v2.0.3 / versionCode 59.

## 2.0.2 stable real concurrency + professional README

- Diagnosed the root cause of the missing v2.0.1 concurrency improvement on Android: `CoreBridge.measureOutboundDelay` is `synchronized(OUTBOUND_PROBE_LOCK)` because AndroidLibXrayLite owns process-wide Go/JNI state, so every Xray HTTP probe was serialized regardless of `SCANNER_PROBE_CONCURRENCY`.
- Rewrote the Android scanner into a two-phase architecture in `AppRepository.importScannerConfigs`:
  - Phase A: parallel TCP handshake delay probe with `SCANNER_TCP_PROBE_CONCURRENCY = 12` sockets on `Dispatchers.IO`, fully JNI-safe because each `java.net.Socket` is a fresh independent instance.
  - Phase B: serial Xray HTTP probe on the top survivors sorted by TCP delay, capped at `SCANNER_NATIVE_CANDIDATE_LIMIT = 96` candidates. Because Phase A already filtered dead hosts, Phase B runs in a fraction of the previous time.
- Added a new `parallelTcpProbe` helper in `AppRepository.kt` and applied the same two-phase split to `enrichScannerRecords` (the post-save modal step), so enrichment is also fast.
- Net effect on a typical 40-candidate scan: Phase A takes 3-5s (parallel), Phase B takes 8-15s (serial but only on 20-30 live candidates), total 15-20s vs 60-90s in v2.0.0/2.0.1.
- Desktop: raised `SCAN_PROBE_QUEUE_LIMIT` from 72 to 120 (capped at `min(120, SCAN_PROBE_WORKERS * 4)`) so the 28-worker `ThreadPoolExecutor` stays fully saturated on heavy scans. Particularly noticeable on macOS and Windows where `xray` process startup overhead is higher.
- Rewrote `README.md` as a comprehensive professional product README (features, install per-platform, architecture diagram, scanner flow with the new two-phase concurrency, cores table, security/SBOM/provenance, languages/RTL, build from source, validation, one-click release, troubleshooting, privacy, contributing, license, acknowledgements) plus GitHub badges.
- Added `parallelTcpProbe` and `SCANNER_TCP_PROBE_CONCURRENCY = 12` checks to `tools/validate_v202_stable.py` and `tests/test_v202_stable.py`.
- Added README comprehensiveness checks (Features, Scanner, real-concurrency, Troubleshooting, License, SBOM sections; minimum 5000 characters) to the validator and tests.
- Bumped version: `RELEASE_VERSION = "2.0.2"`, `versionCode = 58`, `versionName = "2.0.2"`, `APP_VERSION = "2.0.2"` in all three desktop builders, Windows version-info tuple `(2, 0, 2, 0)`, `VERSION` in `build_apk.sh` and `build_apk.bat`.
- Renamed `tools/validate_v201_stable.py` → `tools/validate_v202_stable.py` and `tests/test_v201_stable*.py` → `tests/test_v202_stable*.py`.
- Updated `release.yml`, `DEPLOY_RELEASE_200.bat`, `docs/site/index.html`, `docs/releases/v2.0.2.md`, `dicodePing_android/tools/validate_project.py` to reference v2.0.2 / versionCode 58.

## 2.0.1 stable scanner concurrency + save-then-modal enrichment

- Bumped Android scanner probe concurrency from 1 to 3 (libv2ray JNI-safe) so candidates are tested in parallel instead of one-by-one. ~55% reduction in total scan time on a 40-candidate sample.
- Split the desktop `run_scan` flow: the verified SUB is now committed as soon as stage 2c finishes, without the inline post-save recheck + force-geo refresh that was blocking the "saved" feedback.
- Added a new public `enrich_saved_scanner_records` entry point on desktop that runs the bounded parallel re-probe + force-geo refresh only when the user explicitly accepts the post-save modal.
- Added `ScannerEnrichThread` worker in `dicodeping/workers.py` so the desktop UI stays responsive while enrichment runs.
- Mirrored the same split on Android: `AppRepository.importScannerConfigs` no longer runs the inline post-save re-probe loop; `AppRepository.enrichScannerRecords` is the new public entry point.
- Added `ScannerStage.ENRICHING/ENRICHED`, `ScannerCoordinator.enrichSavedRecords`, and `ScannerState.enrichmentPending` so the Android UI can show the post-save modal exactly once per scan.
- Added `ScannerFragment.showEnrichmentModal` using `MaterialAlertDialogBuilder` with Persian + English strings.
- Added bilingual strings (`scanner_enrich_title`, `scanner_enrich_message`, `scanner_enrich_accept`, `scanner_enrich_reject`, `scanner_enriching`) to `values/strings.xml` and `values-fa/strings.xml`.
- Bumped version: `RELEASE_VERSION = "2.0.1"`, `versionCode = 57`, `versionName = "2.0.1"`, `APP_VERSION = "2.0.1"` in all three desktop builders, Windows version-info tuple `(2, 0, 1, 0)`.
- Renamed `tools/validate_v200_stable.py` → `tools/validate_v201_stable.py` and `tests/test_v200_stable*.py` → `tests/test_v201_stable*.py`; updated the validator and tests to check the new save/enrichment architecture.
- Updated `release.yml`, `DEPLOY_RELEASE_200.bat`, `docs/site/index.html`, `docs/releases/v2.0.1.md` to reference v2.0.1.
- Stable release workflow still runs `workflow_dispatch`, `prerelease: false`, `make_latest: true`, `draft: false`, full `lintStandardRelease`, signed APK assembly, font byte-hash verification, SBOM and provenance.

## 2.0.0 stable Android lint/build hotfix

- Corrected the release lint policy so correctness errors remain fatal while advisory warnings are not promoted into 206 false build errors.
- Fixed runtime locale packaging, bundled Vazirmatn XML compatibility, package visibility, backup rules, accessibility labels, density-correct launcher icons, locale-safe formatting, RecyclerView diff updates, and scoped intentional lint suppressions.
- Kept full `lintStandardRelease`, unit tests, signed APK assembly, native-core verification, and font hash verification in the stable workflow.

# Changelog

## 2.0.0 stable release preflight hotfix

- Removed the undeclared system-PyYAML requirement from the Windows one-click deployer.
- Vendored the pure-Python PyYAML 6.0.3 parser with its MIT license.
- Added strict workflow validation for syntax, duplicate keys, tabs and missing jobs.
- Verified the validator under Python `-S`, with site-packages disabled.

## 2.0.0 — Stable

### Added
- Stable four-platform release for Windows, Linux, macOS and Android.
- Vazirmatn 33.0.3 acquisition with npm SHA-512 integrity verification.
- Packaged desktop startup checks that require `font_family=Vazirmatn`.
- Final post-save SUB verification with fresh TCP/Xray latency and geolocation.
- Minimal responsive Persian download page without screenshots.
- Content-hash verification for optimized Android font resources.

### Fixed
- Removed the obsolete `android:extractNativeLibs` manifest attribute and retained extraction through `jniLibs.useLegacyPackaging`.
- Fixed the Android release failure caused by checking optimized APK font filenames.
- Added the missing Linux `libxcb-shape0` runtime dependency.
- Removed the unsupported Linux PyInstaller icon option.
- Made the release waiter detect `workflow_dispatch` runs and require a published, non-prerelease Latest Release.
- Preserved the macOS DMG retry and verification path for transient DiskImages failures.

### Release quality
- Android lint correctness errors are fatal; advisory warnings remain reported and scoped instead of being promoted blindly.
- Gradle runs with `--warning-mode=fail`.
- Pages deployment is mandatory for the one-click stable release.
- Windows, Linux, macOS ARM64, macOS x86_64 and Android assets are all required before success is reported.

## 1.9.0-rc.16

- Fixed real Aether/Usque startup and HTTP/2 argument ordering on desktop.
- Added atomic WARP registration validation/retry on Android and desktop.
- Made cancellation terminate both WARP registration and active native-core processes immediately.
- Preserved local scanner subscriptions and verified servers across restart and remote-source refresh on all four platforms.
- Added parallel TCP prefiltering and reduced redundant scanner probes for substantially faster scans.
- Reworked Android and desktop live logs to append at the tail without jumping upward.
- Replaced compact duration labels such as `8d`/`2w` with localized human-readable validity badges.
- Bumped Android to versionCode 51 and retained mandatory APK verification for Xray, Aether and Usque on arm64-v8a/x86_64.

## 1.9.0-rc.13

- Routed Android Telegram preview requests through a dedicated loopback SOCKS5 inbound inside the verified Xray instance.
- Prevented scanner traffic from escaping over the device physical IPv6 route while the app UID is excluded from its own VpnService.
- Removed the fragile first-four-channel preflight; every channel is now an independent DicodeConfigChecker-style fetch.
- Kept the canonical `https://t.me/s/<channel>` endpoint with cross-host redirect rejection.
- Added bounded parallel collection, proxy-side DNS, monotonic weighted progress and cancellation of in-flight calls.
- Incremented Android versionCode to 48 and added Stable3 release validation for the SOCKS route and full-crawl behavior.

## 1.9.0-rc.10 Android Lint Hotfix 3

- Marked the English 30% splash status as a non-format Android string resource.
- Prevented `StringFormatInvalid` from blocking the signed Android release after APK assembly.
- Added validator and regression-test coverage for future literal-percent resource strings.


## 1.9.0-rc.10 Xray/Scanner Assurance Hotfix 2

- Waits for asynchronous Android Xray startup instead of rejecting the core immediately.
- Verifies that Xray is still running after the real HTTP tunnel probe.
- Prevents Android from redelivering stale VPN intents after process recreation.
- Resets stale CONNECTING state if the VPN service is destroyed.
- Adds scanner Xray runtime preflight, bounded crawl/probe deadlines, atomic stage-one persistence and a recent-cache fallback.
- Keeps Telegram extraction limited to protocols that ConfigParser and the embedded Xray path can actually execute.


## 1.9.0-rc.10 Android startup/scanner hotfix

- Replaced unbounded Android splash work with source refresh, deterministic 30% per-source quick probes, update check, and a hard fail-open deadline.
- Added Review/Output scanner log tabs with live highlighting and persistent coordinator-backed logs.
- Made Telegram HTTP calls cancellation-aware and reset pooled connections for each VPN-backed scan.
- Serialized every Android Xray JNI lifecycle/probe operation behind one process lock.
- Added APK core inventory checks for Xray, Aether, and Usque on arm64-v8a and x86_64.
- Added mobile press feedback and desktop keyboard/pressed-state feedback.
# Changelog

## 1.9.0-rc.10

- Rebuilt the Telegram collector around the DicodeConfigChecker primary/mirror algorithm.
- Prefer the verified app-owned SOCKS5 route with remote DNS on desktop and keep TUN/direct as fallback.
- Added Telegram route preflight before the full 324-channel crawl.
- Fixed the scanner action remaining on the connecting label after VPN verification.
- Added independent transport timeout budgets and detailed transport-aware live logs.
- Bounded Android crawler concurrency and response memory and added lifecycle-safe per-channel reporting.
- Advanced Android versionCode to 45 and added the Stable0 multi-platform stable release workflow.

## 1.9.0-rc.9 Hotfix 4

- Replaced all seven Android API-26-only `Process` lifecycle calls with API-24-safe compatibility helpers.
- Kept forceful termination on API 26+ while using graceful exit polling on Android 7.x.
- Configured release lint to fail on correctness/security errors and omit legacy advisory warnings from CI output.
- Added always-uploaded HTML, text, and SARIF lint reports for future Android failures.


## 1.9.0-rc.9 Hotfix 3

- Fixed the stale Android automatic-server unit test that blocked release.
- Removed Locale and native-strip warnings from the Android release build.
- Upgraded the active RC9 release workflow to Node 24-compatible actions.
- Allowed automatic connection to start immediately while background ping refresh continues.
- Serialized scanner stop publication and foreground-service teardown.

## 1.9.0-rc.9 Hotfix 2

- Fixed the Android x86_64 Usque build with NDK-backed CGO/external linking.
- Bundled and verified Aether/Usque ELF executables for arm64-v8a and x86_64 inside the APK.
- Serialized Android Xray JNI probes process-wide to prevent libgojni concurrency crashes.
- Hardened scanner foreground-service, VPN-consent, Activity recreation, cancellation, and shutdown paths.
- Made the Android scanner a guarded connect/collect/persist/disconnect/probe/save transaction.
- Expanded automatic connection to eight sequentially verified candidates and accepted every positive real HTTP ping.

## 1.9.0-rc.9

- Reworked the scanner into connect, collect, persist, disconnect, probe, and save stages.
- Bundled the complete DicodeConfigChecker public channel list with rank-aware limits of 8 and 9.
- Added atomic stage-one snapshots before the bootstrap VPN is stopped.
- Added TUN-first Telegram fetching with a bounded SOCKS5 fallback and higher collection capacity.
- Increased real Xray probe capacity and removed the old five-server early exit.
- Added immediate scanner feedback, separate live log streams, and richer server cards.
- Mirrored the staged scanner pipeline on Android.

## 1.9.0 RC7

- Fixed scanner bootstrap ranking so `ConfigQualityResult` objects are never compared directly.
- Added deterministic 30% per-subscription startup testing with an optional full-test prompt after launch.
- Restored dashboard automatic connection with real background Xray quality selection.
- Reworked explicit RTL/LTR sidebar placement and edge alignment across desktop platforms.
- Expanded settings pages to use the full available height and restored visible combo-box arrows.
- Disabled DoH by default for fresh desktop and Android installations.


## 1.9.0 RC7

- Integrated DicodeConfigChecker-style real Xray HTTP verification with repeated samples and median latency.
- Added complete splash-screen source refresh, testing, geolocation and update checks before the UI opens.
- Split scanner logs into All, Telegram and Real tests views with independent live metrics.
- Corrected Persian right-edge and English left-edge sidebar alignment.
- Added Android repeated native-core scanner verification and the single atomic `SUB` lifecycle.
- Added bilingual Persian/English release notes and RC9 multi-platform stable release automation.

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
- Added one-click RC5 Git deployment and existing-stable release recovery.

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

## 1.9.0 Stable

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
- Added `DEPLOY_PRERELEASE_RC4.bat` for one-click GitHub authentication, Android secret setup, clean staging, commit/push, workflow dispatch, run monitoring and stable release opening.
- Changed the RC4 release workflow to `workflow_dispatch` only to prevent duplicate builds after source pushes.

- Hotfix 4: deployment BAT now supports ephemeral classic-token authentication through a hidden prompt, validates repo access, configures Git HTTPS through GitHub CLI, and clears token variables on exit.

- اعتبارسنجی نهایی PR اکنون Check Runها و commit statusها را مستقیماً برای SHA تغییرناپذیر همان Head از GitHub REST API می‌خواند؛ شکست قدیمیِ باقی‌مانده از force-push قبلی نمی‌تواند نتیجه Commit جدید را خراب کند، اما هر شکست واقعی روی SHA جاری همچنان انتشار را متوقف می‌کند.
