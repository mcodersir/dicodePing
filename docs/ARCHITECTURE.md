# Version 3 architecture

## Boundaries

1. **UI** — renders state and invokes application operations only.
2. **Application service** — owns selection, subscription refresh, Scanner persistence and latency state.
3. **Subscription service** — fetches the fixed primary source plus optional user sources.
4. **Runtime client** — newline-delimited JSON RPC boundary between product code and networking runtime.
5. **Desktop runtime host** — owns profile import, config generation, core lifecycle, system proxy, TUN, latency, statistics and logs through ServiceLib.
6. **Android runtime adapter** — translates normalized proxy profiles into Xray runtime configuration and owns Android VpnService integration.

No UI code directly starts Xray, sing-box, Wintun or Android native runtime processes.

## State isolation

Version 3 uses an isolated persistent state namespace so runtime configuration is reproducible from the authoritative subscription source.
