"""Real configuration quality checker used by the scanner.

This module adapts the two-stage verification model from
``mcodersir/DicodeConfigChecker``: supported proxy links are validated by
starting Xray with a temporary local SOCKS inbound and making real HTTP
requests through the selected outbound.  Unsupported links use the same
bounded TCP fallback as the checker project, and are explicitly labelled as
fallback results instead of being presented as full tunnel validation.
"""
from __future__ import annotations

import random
import socket
import statistics
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
    tester: str = "xray-http"
    error: str = ""


def _tcp_connect_delay(host: str, port: int, timeout: float) -> tuple[int | None, str]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return max(1, int(round((time.perf_counter() - started) * 1000))), ""
    except Exception as exc:  # a compact error is enough for the live scanner log
        return None, exc.__class__.__name__


def test_config(
    raw_config: str,
    *,
    attempts: int = 3,
    min_success: int = 2,
    per_attempt_timeout: float = 3.4,
    attempt_gap_seconds: float = 0.12,
    stop_event: threading.Event | None = None,
) -> ConfigQualityResult:
    """Perform repeated, real data-plane validation of one configuration.

    The median successful HTTP round-trip is returned as the user-facing ping.
    A config only passes when at least ``min_success`` attempts succeed.  This
    rejects endpoints that happen to answer one TCP handshake but cannot carry
    stable proxy traffic.
    """
    attempts = max(1, min(5, int(attempts)))
    min_success = max(1, min(attempts, int(min_success)))
    endpoint = parse_endpoint(raw_config)
    if endpoint is None:
        return ConfigQualityResult(False, None, None, None, attempts, 0, error="invalid_config")

    full_tunnel_supported = build_xray_outbound(raw_config) is not None
    tester = "xray-http" if full_tunnel_supported else "tcp-fallback"
    samples: list[int] = []
    errors: list[str] = []

    for index in range(attempts):
        if stop_event is not None and stop_event.is_set():
            return ConfigQualityResult(
                False, None, None, None, attempts, len(samples), tuple(samples), tester, "cancelled"
            )
        if full_tunnel_supported:
            try:
                value = probe_outbound_delay(
                    raw_config,
                    timeout=per_attempt_timeout,
                    cancel_event=stop_event,
                )
                error = "" if value is not None else "http_probe_failed"
            except Exception as exc:
                value = None
                error = exc.__class__.__name__
        else:
            value, error = _tcp_connect_delay(endpoint.host, endpoint.port, min(2.5, per_attempt_timeout))

        if value is not None and value > 0:
            samples.append(int(value))
        elif error:
            errors.append(error)

        # Stop early when success or failure is already mathematically decided.
        remaining = attempts - index - 1
        if len(samples) >= min_success:
            break
        if len(samples) + remaining < min_success:
            break
        if remaining:
            time.sleep(attempt_gap_seconds + random.uniform(0.0, 0.04))

    ok = len(samples) >= min_success
    if not ok:
        return ConfigQualityResult(
            False,
            None,
            None,
            None,
            attempts,
            len(samples),
            tuple(samples),
            tester,
            ";".join(errors[-3:]) or "not_enough_success",
        )

    median_ms = int(statistics.median(samples))
    return ConfigQualityResult(
        True,
        median_ms,
        min(samples),
        int(round(sum(samples) / len(samples))),
        attempts,
        len(samples),
        tuple(samples),
        tester,
        "",
    )
