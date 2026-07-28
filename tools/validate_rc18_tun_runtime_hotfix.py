from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XRAY = ROOT / "dicodeping" / "xray.py"
SERVICE = ROOT / "dicodeping" / "service.py"


def fail(message: str) -> None:
    raise SystemExit(f"RC18 TUN runtime validation failed: {message}")


def main() -> int:
    xray = XRAY.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    ast.parse(xray, filename=str(XRAY))
    ast.parse(service, filename=str(SERVICE))

    if service.count("old.values()") != 1:
        fail("undefined stale-server mapping references remain in service.py")
    if service.index("old = {server.id: server for server in self.store.load_servers()}") > service.index("old.values()"):
        fail("the only old.values() use is not preceded by initialization")

    start = xray[xray.index("    def start("):xray.index("    def traffic_stats(")]
    required = (
        '("www.gstatic.com", "/generate_204", True)',
        "Private SOCKS validation was inconclusive; continuing",
        "A failed private probe must never",
        "_direct_tun_http_probe",
        "use_tls=use_tls",
    )
    missing = [item for item in required if item not in start]
    if missing:
        fail("missing runtime safeguards: " + ", ".join(missing))
    warning_at = start.index("Private SOCKS validation was inconclusive; continuing")
    tun_at = start.index("_direct_tun_http_probe", warning_at)
    if warning_at >= tun_at:
        fail("private SOCKS warning does not continue to TUN verification")
    if "Xray outbound validation failed before TUN verification" in start:
        fail("the old false-negative fatal validation path still exists")

    print("RC18 TUN runtime hotfix validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
