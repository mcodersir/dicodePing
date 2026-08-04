from __future__ import annotations

import ast
import ssl
import threading
from pathlib import Path

from dicodeping import net
from dicodeping.models import ServerRecord


ROOT = Path(__file__).resolve().parents[1]


def _runtime_module():
    # Connectivity code must remain importable on headless Linux runners where
    # QtGui/EGL is intentionally unavailable. UI imports are lazy.
    from dicodeping import rc7_runtime

    return rc7_runtime


def test_connectivity_runtime_has_no_eager_qt_imports() -> None:
    tree = ast.parse((ROOT / "dicodeping/rc7_runtime.py").read_text(encoding="utf-8"))
    eager = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PySide6"):
            eager.append(node.module)
        elif isinstance(node, ast.Import):
            eager.extend(alias.name for alias in node.names if alias.name.startswith("PySide6"))
    assert eager == []


def _record() -> ServerRecord:
    return ServerRecord(
        id="test",
        name="test",
        protocol="VLESS",
        host="example.invalid",
        port=443,
        config_blob="vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        ip="192.0.2.10",
    )


def test_tls_context_keeps_hostname_and_certificate_verification() -> None:
    context = net.create_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert context.cert_store_stats()["x509_ca"] > 0


def test_socks_https_probe_uses_verified_tls_context(monkeypatch) -> None:
    from dicodeping import xray

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, value):
            self.timeout = value

        def sendall(self, value):
            self.request = value

    class FakeTlsStream(FakeSocket):
        pass

    raw = FakeSocket()
    tls = FakeTlsStream()

    class VerifiedContext:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True
        minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED

        def wrap_socket(self, sock, *, server_hostname):
            assert self.minimum_version >= ssl.TLSVersion.TLSv1_2
            assert sock is raw
            assert server_hostname == "www.gstatic.com"
            return tls

    monkeypatch.setattr(xray.socket, "create_connection", lambda *args, **kwargs: raw)
    monkeypatch.setattr(xray, "_socks_connect", lambda *args, **kwargs: True)
    monkeypatch.setattr(xray, "create_tls_context", lambda: VerifiedContext())
    monkeypatch.setattr(xray, "_read_http_status", lambda stream: 204 if stream is tls else None)

    result = xray._socks_http_probe(1080, "www.gstatic.com", "/generate_204", 1.0, use_tls=True)
    assert isinstance(result, int) and result >= 1
    assert b"Host: www.gstatic.com" in tls.request


def test_dead_tcp_endpoint_never_starts_xray(monkeypatch) -> None:
    runtime = _runtime_module()
    calls = 0

    def fail_connect(*args, **kwargs):
        raise OSError("offline")

    def forbidden_probe(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Xray must not start for a dead TCP endpoint")

    monkeypatch.setattr(runtime.socket, "create_connection", fail_connect)
    monkeypatch.setattr(runtime.xray_module, "probe_outbound_delay", forbidden_probe)
    row = _record()
    runtime._test_records([row], {"test_concurrency": 4}, resolve_ips=False)
    assert calls == 0
    assert row.tcp_ms is None
    assert row.ping_ms is None
    assert row.status == "unverified"


def test_desktop_ping_and_geo_workers_start_together(monkeypatch) -> None:
    runtime = _runtime_module()
    barrier = threading.Barrier(2, timeout=1.0)
    started: list[str] = []

    monkeypatch.setattr(runtime, "_resolve_record_ips", lambda *args, **kwargs: None)

    def fake_ping(*args, **kwargs):
        started.append("ping")
        barrier.wait()
        return args[0]

    def fake_geo(*args, **kwargs):
        started.append("geo")
        barrier.wait()
        return args[1]

    monkeypatch.setattr(runtime, "_test_records", fake_ping)
    monkeypatch.setattr(runtime, "_apply_geo", fake_geo)
    runtime._enrich_records_parallel(object(), [_record()], {})
    assert sorted(started) == ["geo", "ping"]
