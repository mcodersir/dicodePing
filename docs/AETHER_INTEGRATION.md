# Aether integration in 2.0.0 stable

- **Android:** native Aether engine is built from the pinned vendored engine snapshot in
  `QW-AI-Code/Aether` for arm64-v8a and x86_64. The engine remains a separate executable (`libaether.so`)
  launched by the app and bridged to Android `VpnService` through the local
  SOCKS/TUN path.
- **Windows, Linux and macOS:** process lifecycle, status transitions,
  cancellation, port-release checks and HTTP/2 fallback follow the design
  patterns reviewed in `MatinSenPai/Aether-GUI`; the shipped engine remains the
  separately licensed Aether core.
- **Unified core orchestration:** `UnboundTechCo/defyxVPN` was reviewed as a
  reference for one-tap, multi-core state handling. No proprietary DXcore
  binary or closed configuration is included.

Aether Mobile and Aether core are AGPL-3.0 projects. Their source locations and
license notices are retained in `THIRD_PARTY_NOTICES.md`.

## Runtime guarantees

- Connection state is not inferred from log phrases; the local SOCKS endpoint
  must accept a connection and pass a real HTTP probe before the UI reports
  Connected.
- Stop requests cancel startup first, terminate the owned process, restore the
  previous system proxy and release the reserved local port.
- QUIC is attempted first and HTTP/2 is used as a bounded fallback when the
  network blocks or throttles UDP.
