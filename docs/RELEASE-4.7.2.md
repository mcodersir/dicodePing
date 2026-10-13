# DicodePing 4.7.2

- Fixed the Fox country dropdown crash when Avalonia recycles a null/empty/unknown country item.
- Fox accounts now create ordinary SOCKS profiles at `socks5://127.0.0.1:7854#Firefox-VPN` with account references stored separately from credentials. Legacy managed profiles retain their identity and normalize at connection time.
- Desktop uses one native sing-box core for the SOCKS-to-TUN path instead of a custom Xray plus a second bridge.
- Dedicated DicodePing Windows adapter names avoid stale/shared adapters; the verified Wintun driver is staged next to the TUN core. A missing-interface startup failure gets one retry with a fresh owned adapter name.
- Connected state waits for native core/TUN initialization. Failures clean up the helper and core and report their diagnostics instead of leaving a false connected state.
- Android uses the same managed SOCKS endpoint, checks the SOCKS handshake, and retains the app package exclusion that protects provider sockets from VPN recursion.
- Copyable SOCKS link on desktop and Android; UDP/443 rejected so browsers can fall back to supported TCP.

Validation includes dropdown recycling checks, native profile migration tests, real local proxy traffic and a live Windows TUN adapter/IP startup test in the release runner. Live Mozilla account availability and behavior on the user's Windows build remain account/device/network dependent. Fox supports TCP and encrypted DNS, not arbitrary UDP.
