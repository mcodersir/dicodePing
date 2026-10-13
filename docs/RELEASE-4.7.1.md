# DicodePing 4.7.1

- Correct HTTP/2 CONNECT lifetime for Firefox startup checks and encrypted DNS.
- REC uses the FoxyVPN Mozilla anycast endpoint before location fallback.
- Fox custom profiles use the sing-box TUN bridge even when legacy protection is off.
- Live upload/download metrics for Xray custom profiles; consistent KiB units and safe counter resets.
- Provider-reported used/remaining allowance updates the existing subscription every minute without replacing profiles or restarting the tunnel.
- Used and remaining quota shown on desktop and Android profile rows; clearer Fox account page.
- One automatic recovery attempt per connection request prevents endless restart loops.
- Null guards for startup statistics and missing default subscriptions.
- Responsive bilingual download page with complete desktop, Android and CLI packages.

Supports TCP and encrypted DNS; arbitrary UDP is not supported by the Fox route. Mozilla controls account eligibility and quota. Validation uses local HTTP/2/SOCKS regression tests and CI builds; actual Mozilla login and reachability depend on the account and network.
