# 4.9.98 upstream issue audit

Base: v4.9.92, commit 0f9aedae0e44e828b1e5aab2ea30b7337bff812d. No 4.9.93/94 code imported.

An upstream report is evidence of a report, not evidence that DicodePing has the same bug. This matrix deliberately distinguishes changes, retained behavior and unverified requests. It is not a list of 40 fixed bugs.

| Report | Subject | Disposition / evidence |
| --- | --- | --- |
| [2dust/v2rayNG #6305](https://github.com/2dust/v2rayNG/issues/6305) | [Feature Request] Support Xdrive transport configuration and link parsing | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6378](https://github.com/2dust/v2rayNG/issues/6378) | [Bug] Policy group shared in a subscription (`v2rayn://` line) is duplicated on every subscription update | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6384](https://github.com/2dust/v2rayNG/issues/6384) | [Bug] Hysteria 2 upload speed severely capped at ~3 Mbps in 2.3.x (Works perfectly in 2.2.6) | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6386](https://github.com/2dust/v2rayNG/issues/6386) | Incomplete issue report containing a profile link | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6388](https://github.com/2dust/v2rayNG/issues/6388) | Setting to strip "inbound" for custom JSON | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6389](https://github.com/2dust/v2rayNG/issues/6389) | 链式代理输入部分节点名称不出现候选节点 | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6392](https://github.com/2dust/v2rayNG/issues/6392) | 链式代理，落地机使用socks5和ss时，能测试通延迟，但是无法访问任何网站 | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6397](https://github.com/2dust/v2rayNG/issues/6397) | [Feature Request] 希望支持将策略组固定在节点列表顶部（置顶显示） | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6403](https://github.com/2dust/v2rayNG/issues/6403) | [Feature Request] Support Multiple Parallel Tunnels with Load Balancing | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayNG #6404](https://github.com/2dust/v2rayNG/issues/6404) | UI change proposal, about the Subscription info panel | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayN #10063](https://github.com/2dust/v2rayN/issues/10063) | [Bug]: 闪退崩溃 | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayN #10456](https://github.com/2dust/v2rayN/issues/10456) | [Bug]: 最新代码编译后,节点测试数据无法保存,guiNDB中ProfileExItem表不更新 | Same persistence defect as PattN #41; same local fix. |
| [2dust/v2rayN #10518](https://github.com/2dust/v2rayN/issues/10518) | [RFC/Proposal] Bind Xray outbound socket to physical interface in dual-core TUN mode to completely eliminate routing loops (#9974) and double-hop latency | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayN #10522](https://github.com/2dust/v2rayN/issues/10522) | [Bug]: macOS 开机自启实例在「参数设置」点保存即自杀式退出（AutoStartupHandler 用 launchctl unload -w 卸载自身所在的 LaunchAgent） | Changed: write next-login registration without unloading own LaunchAgent. macOS acceptance pending. |
| [2dust/v2rayN #10523](https://github.com/2dust/v2rayN/issues/10523) | [Bug]: [macOS] TUN mode: switching from a sing-box-core node (Hysteria2) to an Xray-core node fails with "address already in use" on 127.0.0.1:10808 — leftover root sing-box process | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayN #10524](https://github.com/2dust/v2rayN/issues/10524) | Windows desktop 版本，在字体大小切换时会崩溃 | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayN #10525](https://github.com/2dust/v2rayN/issues/10525) | [Feature request]: 真连接延迟-1的bug和解决方法 | Changed: isolated bounded retry for failed latency, skip throughput on failed routes. Native acceptance pending. |
| [2dust/v2rayN #9876](https://github.com/2dust/v2rayN/issues/9876) | [Bug]: MacOS Arm架构7.24.4版本下开启EnableDragDropSort后使用鼠标点击节点列表程序崩溃 | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayN #9899](https://github.com/2dust/v2rayN/issues/9899) | [Bug]: 只要用一段时间，不是必现Bug，就无法显示窗体 | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [2dust/v2rayN #9915](https://github.com/2dust/v2rayN/issues/9915) | [Bug]: 切换页面崩溃 | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [Vauth/FoxyVPN #32](https://github.com/Vauth/FoxyVPN/issues/32) | [Feature Request] Built-in scanner for Custom Edge IPs | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [Vauth/FoxyVPN #37](https://github.com/Vauth/FoxyVPN/issues/37) | Auto-Connect on Internet | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [Vauth/FoxyVPN #61](https://github.com/Vauth/FoxyVPN/issues/61) | Harmful App | No REQUEST_INSTALL_PACKAGES permission added. Third-party malware classifications cannot be promised resolved. |
| [Vauth/FoxyVPN #63](https://github.com/Vauth/FoxyVPN/issues/63) | local lan connection not working | Existing explicit local-proxy sharing preference retained; no public listener enabled by default. |
| [Vauth/FoxyVPN #64](https://github.com/Vauth/FoxyVPN/issues/64) | [Feature Request] Make IPv4/IPv6 preference apply only to Fastly edge nodes (not globally) | No global forced IP family added. Existing Fox engine preserved. |
| [Vauth/FoxyVPN #66](https://github.com/Vauth/FoxyVPN/issues/66) | TFO | No TFO option in retained engine. No core change. |
| [Vauth/FoxyVPN #68](https://github.com/Vauth/FoxyVPN/issues/68) | Not HTTP/3 | No HTTP/3 claim: retained engine uses HTTP/2 explicitly; no new Fox core or silent H3 label. |
| [Vauth/FoxyVPN #69](https://github.com/Vauth/FoxyVPN/issues/69) | `vpn.mozilla.org` DNS lookup does not go through DoH | 4.9.92 Fox control and edge TLS already use secure bootstrap (edge.go); original engine preserved. Regression suite passes. |
| [patterniha/PattNG #45](https://github.com/patterniha/PattNG/issues/45) | PattNG+Aether on PC+Android(New Method) | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattNG #46](https://github.com/patterniha/PattNG/issues/46) | [Feature Request] Support XDRIVE transport in UI forms and VLESS share links | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattNG #47](https://github.com/patterniha/PattNG/issues/47) | Feature request: Allow the Connect button to be activated with an Android TV remote | TV build: initial focus on connection button and visible D-pad focus. Device acceptance pending. |
| [patterniha/PattNG #51](https://github.com/patterniha/PattNG/issues/51) | [FR] Auto check after connect | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattNG #54](https://github.com/patterniha/PattNG/issues/54) | آپدیت نشدن لینک ساب | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattN #23](https://github.com/patterniha/PattN/issues/23) | [Feature request]: پیشنهاد جدید | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattN #31](https://github.com/patterniha/PattN/issues/31) | [Feature request]: پیشنهاد اضافه شدن گزینه بای‌پاس SNI-Block و اعمال خودکار تنظیمات TLS/Cipher در به‌‌روزرسانی سابسکرایب‌ها | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattN #34](https://github.com/patterniha/PattN/issues/34) | [Feature request]: Any Outer SNI can be used for Cloudflare ECH as long as it's behind Orange Cloud. | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattN #36](https://github.com/patterniha/PattN/issues/36) | [Feature request]: Reproducible standalone Windows MASQUE-H2 support | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattN #37](https://github.com/patterniha/PattN/issues/37) | [Feature Request] Support XDRIVE transport in UI forms and VLESS share links | Reviewed; not reproduced or implemented as a new fix in this release. See scope below. |
| [patterniha/PattN #40](https://github.com/patterniha/PattN/issues/40) | [Feature request]: Compile with older GLIBC | DEB avoids upstream minimum GLIBC dependency pins. Older-distribution execution not verified. |
| [patterniha/PattN #41](https://github.com/patterniha/PattN/issues/41) | [Bug]: Real Delay results are not persisted after app restart - نتایج Real Delay بعد از بستن برنامه پاک می‌شود | Changed: de-duplicate IDs within each SQLite flush. Existing persistence tests pass; high-contention restart acceptance remains required. |

## Scope still pending

XDRIVE form/link authoring, parallel load-balanced tunnels, policy-group pinning, subscription-header scrolling, OS-specific Skia/window/drag failures, and network-specific TLS/MASQUE or Hysteria throughput reports require dedicated implementation or reproduction. Custom Xray JSON remains available. Never disable certificate verification to hide a trust failure. Existing SNI bypass / final-mask / interface binding / Aether chaining features remain available; their presence is not new proof of every linked issue being fixed.

FoxyVPN 2.0.0 was reviewed at e692202dbdf0a5dbbff8ce8bba000f62a9039451; 2.0.1 release metadata was also inspected for the listed reports. Its replacement sing-box MASQUE engine was intentionally not imported. apps/fox-helper is byte-for-byte unchanged from v4.9.92.

## Test status before CI

- Original Fox engine: go test -race ./... passed on Linux with Go 1.27.3.
- Desktop tests: 229 passed, 12 skipped (native fixtures/platform prerequisites absent), 0 failed.
- Desktop graphical build: succeeded, 0 errors.
- Android, TV, Windows and macOS runtime acceptance: pending CI/device checks.
- Iran-specific carrier reachability, battery, RAM and speed: not measured; no performance percentage or universal reachability claim.

## Additional validation

- The current Serverless-for-Iran v58 fragA, fragB and oob JSON configurations were fetched and accepted by the actual pinned Xray 26.11.1 binary (`run -test`); this is configuration validation, not an Iran carrier connectivity test.
- Ten generated configurations were accepted by actual Xray/sing-box binaries on Linux.
- Fifteen focused desktop regression tests passed, including a database flush containing duplicate IDs.
- The independent sing-box traffic fixture could not start locally because this workspace denies netlink sockets. The same fixture is required on the release runners; local denial is not counted as a successful traffic test.
- The provided desktop 4.9.93 log shows subscription timeouts/refused localhost connections and destination DNS timeouts, alongside a successful v58-fragA probe. These entries do not establish a single universal root cause or prove Android behavior. No TLS verification bypass was added.

Latest full desktop run: 230 passed, 16 skipped for missing native/platform prerequisites, 0 failed (246 total). The separate native configuration run passed all 10 cases.

## Browser verification follow-up

FoxyVPN 2 exchanges the confirmed FxA session for OAuth tokens inside its sign-in WebView. DicodePing previously handed that session to the native helper, using a separate HTTP/browser identity. Both clients now perform the standard Hawk-signed exchange on the official browser page, then save the grant in the existing encrypted account vault. The original helper is unchanged and remains the fallback when browser crypto/network support is unavailable.

The Chromium regression failed against the previous bridge and passed against this implementation. It independently checks the Hawk HKDF, payload hash and MAC, rejects errno 104, verifies retry, rotated sessions and full-page verification redirects, and prevents foreign-origin handoff. Desktop grant parser tests cover nonce/origin binding, invalid payloads, pending sessions and page readiness. Native platform fixtures exercise the bridge using test-only OAuth responses; these are not proof of a live Mozilla account login. Mandatory Mozilla verification is not bypassed.

The Android 14 TV attempt lost its emulator connection after a successful cold launch; subsequent logcat began at a new system boot. It is recorded as an emulator restart, not a proven app crash. Signed installation/remote navigation remains a required release gate.

Android grant validation was separated from Android's stubbed JVM JSONObject implementation. The three actual Kotlin/JVM tests passed under Kotlin 2.4.21, including missing refresh tokens and malformed grant rejection. The previous test failure was the Android JSON stub, not a failed device sign-in.

Mihomo's rolling prerelease removed the alpha-9002a4f assets during the build. The current alpha-478af2a artifacts were downloaded for all four desktop targets and independently SHA-256 verified against official GitHub release digests; the Linux executable reports the expected version. The immutable source commit is recorded in the runtime manifest.
