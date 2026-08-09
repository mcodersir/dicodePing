"""Real dual-path configuration checker for the desktop scanner.

Every candidate receives exactly two independent measurements:
1. one TCP handshake to the endpoint (reachability / network RTT), and
2. one HTTP request routed through the candidate's own Xray outbound.

Only the Xray result can mark a configuration healthy.  A fast open TCP port
is never presented as proof that credentials, TLS, Reality or transport work.
"""
from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field

from .protocols import build_xray_outbound, parse_endpoint
from .xray import probe_outbound_delay


@dataclass(frozen=True)
class ConfigQualityResult:
    ok: bool
    ping_ms: int | None
    min_ms: int | None
    avg_ms: int | None
    attempts: int
    success_count: int
    samples_ms: tuple[int, ...] = field(default_factory=tuple)
    tester: str = "tcp+xray-http"
    error: str = ""
    tcp_ms: int | None = None


def _tcp_connect_delay(host: str, port: int, timeout: float) -> tuple[int | None, str]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            elapsed = max(1, int(round((time.perf_counter() - started) * 1000)))
            return elapsed, ""
    except Exception as exc:
        return None, exc.__class__.__name__


def test_config(
    raw_config: str,
    *,
    attempts: int = 1,
    min_success: int = 1,
    per_attempt_timeout: float = 3.4,
    attempt_gap_seconds: float = 0.0,
    stop_event: threading.Event | None = None,
) -> ConfigQualityResult:
    """Run one TCP test and one real Xray HTTP test.

    ``attempts`` and ``min_success`` remain accepted for API compatibility, but
    RC19 deliberately performs one sample per path so the UI values have clear,
    repeatable semantics and scanning does not multiply network work silently.
    """
    del attempts, min_success, attempt_gap_seconds
    endpoint = parse_endpoint(raw_config)
    if endpoint is None:
        return ConfigQualityResult(False, None, None, None, 1, 0, error="invalid_config")
    if stop_event is not None and stop_event.is_set():
        return ConfigQualityResult(False, None, None, None, 1, 0, error="cancelled")

    tcp_ms, tcp_error = _tcp_connect_delay(
        endpoint.host,
        endpoint.port,
        min(2.5, max(0.5, float(per_attempt_timeout))),
    )
    if stop_event is not None and stop_event.is_set():
        return ConfigQualityResult(
            False, None, None, None, 1, 0, error="cancelled", tcp_ms=tcp_ms
        )

    if build_xray_outbound(raw_config) is None:
        return ConfigQualityResult(
            False,
            None,
            None,
            None,
            1,
            0,
            tester="tcp+xray-unsupported",
            error="xray_outbound_unsupported" + (f";tcp={tcp_error}" if tcp_error else ""),
            tcp_ms=tcp_ms,
        )

    try:
        xray_ms = probe_outbound_delay(
            raw_config,
            timeout=max(1.0, float(per_attempt_timeout)),
            cancel_event=stop_event,
        )
        xray_error = "" if xray_ms is not None else "xray_http_probe_failed"
    except Exception as exc:
        xray_ms = None
        xray_error = exc.__class__.__name__

    if xray_ms is None or int(xray_ms) <= 0:
        errors = [part for part in (xray_error, f"tcp={tcp_error}" if tcp_error else "") if part]
        return ConfigQualityResult(
            False, None, None, None, 1, 0,
            tester="tcp+xray-http",
            error=";".join(errors) or "xray_http_probe_failed",
            tcp_ms=tcp_ms,
        )

    value = int(xray_ms)
    return ConfigQualityResult(
        True,
        value,
        value,
        value,
        1,
        1,
        (value,),
        "tcp+xray-http",
        "",
        tcp_ms,
    )
