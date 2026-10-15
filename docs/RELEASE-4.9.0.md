# DicodePing 4.9.0

- Desktop startup failures are reported once by the connection flow; failed background probe launches stay in diagnostic logs.
- Desktop core starts, replacements and stops are serialized. The Best action locks its complete test/select/connect operation; diagnostics keep independent ports. If the requested mixed listener port is occupied, the runtime chooses a free local port and system-proxy consumers follow that active port.
- Explicit desktop connection requests wait for an in-flight reload instead of returning an early failure. Fox page starts enable the same TUN mode as Home/Best.
- Main and TUN bridge configurations are compared together before reusing a connection. Settings snapshots keep bridge and main listener ports consistent.
- Each Windows sing-box TUN launch uses a fresh DicodePing-owned adapter name. The reported stale-adapter create/open collision gets one bounded retry. Other VPN adapters and routes are never removed.
- Windows automatically selects an active Ethernet/Wi-Fi uplink with an IPv4 gateway, excludes common virtual/VPN adapters, and orders candidates by default route/interface metrics. A manually selected interface takes precedence. Core, bootstrap DNS and Fox relay sockets use the selected uplink.
- Desktop traffic collectors use the active runtime's frozen metrics port, profile and session. Local statistics bypass system proxy settings; samples from an ended session are discarded.
- Android Best sends an explicit profile connection request rather than a state-dependent toggle. Network monitoring requests a non-VPN upstream and ignores late loss/capability events from the previous uplink.
- Android version code increases while retaining package identity, account storage and release signing configuration. Desktop, Android and CLI packages retain the pinned native runtimes from 4.8.0.

Fox is an unofficial Firefox VPN integration. Provider eligibility, authentication and quota remain controlled by Mozilla. It supports TCP and encrypted DNS, not arbitrary UDP. Android permits one active VpnService per user: starting DicodePing replaces another VPN rather than combining two device tunnels.

Verification includes unit regressions for port snapshots, adapter ownership/collision recovery and physical uplink filtering, Android upstream handover regression, Go relay tests, and the existing release checks for native core configuration and routed Windows TUN traffic. A local fixture or emulator does not establish connectivity to a user's live Mozilla account or reproduce every installed VPN driver.
