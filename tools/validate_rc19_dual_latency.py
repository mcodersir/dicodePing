from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"RC19 dual-latency validation failed: {message}")

models = read("dicodeping/models.py")
checker = read("dicodeping/config_checker.py")
scanner = read("dicodeping/scanner.py")
runtime = read("dicodeping/rc7_runtime.py")
ui = read("dicodeping/ui.py")

require("tcp_ms: int | None" in models, "ServerRecord must persist tcp_ms")
require("socket.create_connection" in checker, "scanner must perform TCP handshake")
require("probe_outbound_delay" in checker, "scanner must perform real Xray probe")
require("SCAN_PROBE_ATTEMPTS = 1" in scanner, "scanner must run one sample per path")
require("SCAN_PROBE_RETRY_LIMIT = 0" in scanner, "scanner must not silently repeat tests")
require("row.tcp_ms = tcp_ms" in runtime, "desktop refresh must persist TCP latency")
require("row.ping_ms, row.status" in runtime, "Xray result must own health state")
require("QTableWidget(0, 9)" in ui, "desktop list must have separate TCP/Xray columns")
require('self.t("tcp_ping")' in ui and 'self.t("xray_ping")' in ui, "latency headers missing")
require("latency_badge_widget" in ui, "colored latency badge widget missing")
print("RC19 dual TCP/Xray latency validation passed")
