# Real-device test matrix

| Area | Windows | Android | Acceptance |
|---|---|---|---|
| Cold connect | Windows 10 22H2, Windows 11 current | API 26, 29, 31, 34, current API | Connected state only after real HTTPS probe succeeds |
| IPv4 | Ethernet, Wi-Fi, hotspot | Wi-Fi, LTE/5G | Public IP changes; no direct route |
| IPv6 | Native dual-stack and IPv6-only/NAT64 when available | Dual-stack Wi-Fi and mobile | No IPv6 bypass; either tunneled or deliberately fail-closed |
| DNS | system resolver and DoH configuration | private DNS on/off | No resolver outside declared policy |
| Handover | Wi-Fi to Ethernet/hotspot | Wi-Fi to mobile and back | bounded reconnect; no stale VPN interface |
| Lifecycle | logout/sleep/reboot | revoke VPN, force-stop, process kill, reboot | core, ports, routes, notification, and interface cleaned up |
| Server list | valid, empty, malformed, 5 MB, duplicate | same | size/time limits, schema validation, deterministic dedupe |
| Ping/ranking | blocked ICMP, open port/bad credential, slow TLS | same | bad proxy never wins; median and jitter used |
| UI | 1, 100, 1,000 profiles | same | no main-thread network work; responsive scrolling/animation |
| Failure | DNS timeout, TLS error, core crash, port collision | same | clear error, no infinite spinner, retry is bounded |
