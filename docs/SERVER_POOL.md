# Server pool (3.9.0 preview)

Open **استخر سرورها** from the desktop menu or Android navigation drawer and start collection.
Android requests the normal system VPN permission when necessary.

1. Refresh the existing Dicode Config Checker subscription and test its profiles through the core.
2. Connect to its fastest responding profile. Fetch the channel index and Telegram public previews through the local proxy.
3. Read the newest available link-bearing posts first, accepting at most four VMess, VLESS, Trojan or Shadowsocks links per channel. Source dates appear in diagnostics; candidates are not silently rejected because of a seven-day cutoff or an incorrect device clock. Undated posts and Telegram MTProto proxies are excluded. Private/unavailable channels count as errors without aborting other channels.
4. Probe each candidate three times through its own outbound. All three samples must be positive and at most 900 ms; rank accepted routes by median latency.
5. Replace profiles in the independent **سرور های استخر** group only after successful validation. This group is created when the page opens; the previous pool name migrates under the same stable ID. Existing user subscriptions remain separate. Cancellation or no accepted candidates preserves the previous pool.

Downloads are limited to eight concurrent requests, 15 seconds and 2 MiB per response. Desktop tests use batches of twelve routes with six concurrent HTTP probes; Android allows four concurrent native tests. The page shows progress and supports cancellation. Reopening the page displays the saved pool; press refresh to collect current configurations again. Collection does not run on a background schedule.

Desktop publication uses a SQLite transaction; Android uses the existing locked, payload-first profile index replacement. An actively selected old profile is protected by the existing selection preservation rules. Configuration links and credentials are not written to the progress display.

## Upstream integration

- PattNG `2.3.10-P60`, commit `7dbdf0cfc2971709b4d47f202a66e05e974ca1c9`.
- AndroidLibXrayLite `v26.10.4`, commit `dc2d0b1388808fa10916fd212907befd6723e553`; AAR SHA-256 `086e7c3e74c0d0e5365215b0e17597b4b8449741fb0655b141879dd4420b074f`.
- hev-socks5-tunnel revision pinned by PattNG P60.
- Desktop uses `XTLS/Xray-core v26.9.30`, `SagerNet/sing-box v1.14.2` and `MetaCubeX/mihomo v1.19.32`, with each platform archive pinned by SHA-256 in the release workflow.

P60 changes are consumed through the release workflow native build while preserving Dicode's branding, subscription usage fields, always-on traffic counters, domain filters, sanctions tests and main-screen layout. The upstream main-screen row-model rewrite remains intentionally excluded where it conflicts with Dicode-specific desktop and Android fields.

Network reachability depends on the device, ISP and the public channels at collection time. CI checks parsing, validation, application builds and core startup; it does not certify connectivity on every user's network.

## Revision 2

Connection startup now awaits daemon acknowledgement (Android) or the desktop reload operation and local listener readiness. Fetching a GitHub file is no longer a two-second VPN health check. Source downloads have independent retries across GitHub raw, repository raw and raw-content API endpoints; failures retain the source stage. Three strict samples remain required, and desktop test listeners must be ready before measurement begins.

Both pages display timestamped live diagnostics (bounded to 300 entries), per-round latency, progress, saved results, cancellation, rerun, copy and auto-scroll controls. Android base versionCode is 309001 and desktop FileVersion is 3.9.0.2; the displayed release remains 3.9.0.

## Revision 3

The parser supports class/attribute variations, numeric HTML entities and inline formatting. Collection reports missing previews, unreadable dates and absence of direct V2Ray links separately. Zero extracted or importable candidates stops at collection/import, without pretending a ping ran. Release CI captures bounded public Telegram responses and exercises both production parsers against them; deterministic tests cover expired cutoff dates, HTML variation and subscription isolation. Android base versionCode is 309002 and desktop FileVersion is 3.9.0.3.
