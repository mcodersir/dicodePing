# DicodePing 4.8.0

- Windows ordinary Xray profiles use the supported sing-box SOCKS/TUN bridge instead of starting the failing shared Xray TUN adapter. Connection state waits for the complete bridge startup.
- Desktop Xray updated to checksum-pinned v26.10.13. Android retains PattNG 2.3.10-P63's verified native runtime.
- The desktop profile-row connection button starts or switches the route. Android Fox profile selection starts the service, including legacy managed profiles, without visiting the Fox page.
- Fox profiles run in isolated helper-backed probes, including TCP-test actions; testing a stopped local port is no longer reported as the Fox ping. Each isolated desktop probe allocates a fresh local port, so it can run beside an active Fox connection without taking port 7854 or stopping its helper.
- Xray's primary traffic counters remain the statistics source while sing-box owns TUN. Loopback metrics requests bypass system proxies. Sing-box retains partial bytes across samples instead of dropping low-rate traffic through per-second KiB rounding.
- Download site updated for 4.8.0 across desktop, Android and CLI.

Regression validation includes real HTTP through a Windows kernel TUN route, sing-box, Xray and an isolated SOCKS fixture, with nonzero upload/download metrics. This uses a single benchmark destination route, not the runner's global default routes. Android native tests use local traffic fixtures. Live Mozilla account and the user's Windows preview build still require device/account validation.
