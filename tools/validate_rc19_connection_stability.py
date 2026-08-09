from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"RC19 connection-stability validation failed: {message}")

xray = read("dicodeping/xray.py")
workers = read("dicodeping/workers.py")
manager = read("dicodeping/connection_manager.py")

start = xray[xray.index("    def start("):xray.index("    def traffic_stats(")]
post = workers[workers.index("def _tunnel_passes_real_traffic"):workers.index("\n\nclass TaskThread")]

require("_DIRECT_TUN_ENDPOINTS" in xray, "diverse direct TUN endpoints are missing")
require("_SOCKS_VALIDATION_TARGETS" in xray, "private Xray validation targets are missing")
require("verification_deadline = verification_started + 13.0" in start, "startup validation must have a bounded total budget")
require('evidence = "tun-traffic"' in start, "real TUN traffic evidence is missing")
require('evidence = "tun-http"' in start, "direct TUN HTTP evidence is missing")
require('evidence = "xray-socks+configured-tun"' in start, "Xray outbound fallback evidence is missing")
require("self._startup_verified = True" in start, "successful startup evidence is not persisted")
require("startup_evidence" in manager and "startup_verified" in manager, "ConnectionManager does not expose startup evidence")
require("return self.startup_verified" in manager, "ConnectionManager verification must use Xray startup evidence")
require('getattr(manager, "startup_verified", False)' in post, "post-start worker must trust verified startup")
require("is_any_url_reachable_parallel" not in post, "redundant fatal public URL validation survived")
require("for wait in" not in post, "old multi-wait post-start failure loop survived")
require("time.monotonic() - self._last_verified_at <= 90.0" in xray, "latency flap grace window is missing")
print("RC19 desktop connection stability validation passed")
