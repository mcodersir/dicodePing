# 4.4 runtime and migration provenance

Android source: PattNG tag `2.3.10-P63`, commit `d50168fbcb03daf12706096fb0391347b93d172d`. Three-way migration against the previous integrated P42 commit retains Dicode identity, defaults, metrics and pool functionality. Checked P63 storage operations back the compatibility APIs.

Desktop source: PattN `7.25.5-P32` / `694993a`; source comparison against P31 found no C# or ResUI delta. The runtime, process-routing and connection/preparation fixes are implemented in this repository.

`runtime-pins-4.4.0.json` records release asset hashes. CI validates the Android AAR and all desktop runtimes, executes each bundled desktop core and validates generated standard, TUN, isolated probe, entry-hop, custom-probe and SNI configurations against those binaries. Android preflight runs the unit tests and D-pad traversal/activation instrumentation before tagging.

Transport success means a real successful HTTP request through the local SOCKS proxy; an open port or successful helper startup is not sufficient. Discovery stores no new credentials. Existing connection credentials remain in the normal profile/identity stores. Failed helpers are reported; no implicit direct fallback is introduced.

FinalMask scanning uses only fragment modes implemented by the pinned Xray fork. `unsafe` selects its native TLS ClientHello implementation; it does not change `allowInsecure`. Desync is unsupported and has no fake toggle.

On Android the optional transport scan targets settings-based Aether profiles. Existing chains can use them as entry hops through the P63 chain editor. Cached transport is scoped to network identity and reused on the next user start; rescan is also available in the main menu. Runtime handover keeps upstream behavior; discovery does not alter a live VPN automatically.
