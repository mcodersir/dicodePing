from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from dicodeping.constants import DEFAULT_SUBSCRIPTION_URL, XRAY_VERSION
from dicodeping.discovery import normalize_subscription_urls
from dicodeping.models import DiscoveredConfig
from dicodeping.net import PingResult, resolve_all_ips, resolve_all_ipv4
from dicodeping.protocols import blob_to_config, build_xray_outbound, decode_subscription, normalize_key, parse_endpoint
from dicodeping.service import ServerService
from dicodeping.sources import normalize_sources, serialize_sources
from dicodeping.xray import (
    TUN_NAME,
    XrayManager,
    _parse_sha256_digest,
    _core_version_matches,
    _pinned_asset_url,
    build_tun_config,
    ensure_wintun,
    normalize_bypass_domains,
)


class FakeStore:
    def __init__(self) -> None:
        self.servers = []

    def load_servers(self):
        return list(self.servers)

    def save_servers(self, servers):
        self.servers = list(servers)

    def load_geo_cache(self):
        return {}

    def save_geo_cache(self, cache):
        pass


class FakeGeo:
    def resolve_many(self, ips, callback=None):
        return {ip: {"country": "Germany", "country_code": "DE", "city": "Frankfurt", "isp": "Test"} for ip in ips}


class ProtocolTests(unittest.TestCase):
    def test_default_subscription_uses_cache_after_network_failure(self) -> None:
        from unittest.mock import patch
        from dicodeping.discovery import _fetch_subscription, _subscription_cache_path
        from dicodeping.models import SourceDefinition

        source = SourceDefinition("default-test", "Test", DEFAULT_SUBSCRIPTION_URL, 0, True, True)
        path = _subscription_cache_path(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("vless://uuid@example.com:443?security=tls#cached", encoding="utf-8")
        with patch("dicodeping.discovery.fetch_text", side_effect=OSError("DNS unavailable")):
            rows = _fetch_subscription(source)
        self.assertEqual(rows, ["vless://uuid@example.com:443?security=tls#cached"])
        path.unlink(missing_ok=True)

    def test_endpoint_resolution_keeps_ipv6_for_tcp_probes(self) -> None:
        rows = [
            (2, 1, 6, "", ("192.0.2.1", 0)),
            (10, 1, 6, "", ("2001:db8::1", 0, 0, 0)),
        ]
        with patch("dicodeping.net.socket.getaddrinfo", return_value=rows):
            self.assertEqual(resolve_all_ips("example.test"), ["192.0.2.1", "2001:db8::1"])
            self.assertEqual(resolve_all_ipv4("example.test"), ["192.0.2.1"])

    def test_xray_core_version_must_match_pinned_release(self) -> None:
        current = subprocess.CompletedProcess([], 0, stdout=f"Xray {XRAY_VERSION} (test)", stderr="")
        stale = subprocess.CompletedProcess([], 0, stdout="Xray 25.1.1 (test)", stderr="")
        with patch("dicodeping.xray.subprocess.run", return_value=current):
            self.assertTrue(_core_version_matches(Path("xray")))
        with patch("dicodeping.xray.subprocess.run", return_value=stale):
            self.assertFalse(_core_version_matches(Path("xray")))

    def test_xray_download_is_version_pinned_and_digest_parsed(self) -> None:
        with patch("dicodeping.xray._asset_name", return_value="Xray-windows-64.zip"):
            name, url = _pinned_asset_url()
        self.assertEqual(name, "Xray-windows-64.zip")
        self.assertIn(f"/v{XRAY_VERSION}/", url)
        digest = "a" * 64
        self.assertEqual(_parse_sha256_digest(f"SHA2-256={digest}\n"), digest)
        with self.assertRaises(RuntimeError):
            _parse_sha256_digest("SHA1=deadbeef")

    def test_vless_parse_and_outbound(self) -> None:
        raw = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls&type=ws&host=example.com&path=%2Fws#test"
        endpoint = parse_endpoint(raw)
        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint.host, "example.com")
        outbound = build_xray_outbound(raw)
        self.assertEqual(outbound["protocol"], "vless")
        self.assertEqual(outbound["streamSettings"]["network"], "ws")

    def test_base64_subscription(self) -> None:
        raw = "trojan://password@example.com:443?security=tls#one"
        encoded = base64.b64encode(raw.encode()).decode()
        self.assertEqual(decode_subscription(encoded), [raw])

    def test_tun_config_is_tun_only(self) -> None:
        raw = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls&type=tcp#test"
        config = build_tun_config(raw)
        self.assertEqual(len(config["inbounds"]), 1)
        self.assertEqual(config["inbounds"][0]["protocol"], "tun")
        self.assertEqual(config["inbounds"][0]["settings"]["name"], TUN_NAME)
        self.assertIn("0.0.0.0/0", config["inbounds"][0]["settings"]["autoSystemRoutingTable"])
        self.assertEqual(config["inbounds"][0]["settings"]["mtu"], 1400)
        self.assertEqual(config["outbounds"][0]["streamSettings"]["sockopt"]["domainStrategy"], "UseIP")
        self.assertEqual(config["outbounds"][0]["streamSettings"]["sockopt"]["tcpKeepAliveIdle"], 45)

    def test_tun_config_enables_stats_and_direct_domains(self) -> None:
        raw = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls&type=tcp#test"
        config = build_tun_config(raw, ["https://www.digikala.com/search/", "domain:aparat.com"], api_port=10085)
        self.assertEqual(config["routing"]["rules"][0]["outboundTag"], "direct")
        self.assertEqual(config["routing"]["rules"][0]["domain"], ["domain:digikala.com", "domain:aparat.com"])
        self.assertEqual(config["api"]["listen"], "127.0.0.1:10085")
        self.assertIn("StatsService", config["api"]["services"])
        self.assertTrue(config["policy"]["system"]["statsInboundDownlink"])

    def test_bypass_domain_normalization(self) -> None:
        values = "https://example.com/path\n*.sub.example.org\nnot-a-domain\nEXAMPLE.com"
        self.assertEqual(normalize_bypass_domains(values), ["example.com", "sub.example.org"])

    def test_traffic_stats_reads_tun_totals(self) -> None:
        class AliveProcess:
            @staticmethod
            def poll():
                return None

        manager = XrayManager()
        manager.process = AliveProcess()
        manager.executable = Path("xray")
        manager.api_port = 10085
        payload = {
            "stat": [
                {"name": "inbound>>>tun-in>>>traffic>>>uplink", "value": "2048"},
                {"name": "inbound>>>tun-in>>>traffic>>>downlink", "value": "4096"},
                {"name": "inbound>>>api>>>traffic>>>downlink", "value": "999"},
            ]
        }
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
        with patch("dicodeping.xray.subprocess.run", return_value=completed):
            self.assertEqual(manager.traffic_stats(), (2048, 4096))
        manager.process = None

    def test_space_separated_subscription(self) -> None:
        one = "vless://11111111-1111-1111-1111-111111111111@one.example:443?security=tls#one"
        two = "trojan://password@two.example:443?security=tls#two"
        self.assertEqual(decode_subscription(one + " " + two), [one, two])

    def test_vmess_name_is_not_part_of_identity(self) -> None:
        base = {"v": "2", "ps": "source-a", "add": "example.com", "port": "443", "id": "11111111-1111-1111-1111-111111111111", "net": "tcp"}
        one = "vmess://" + base64.b64encode(__import__("json").dumps(base).encode()).decode()
        base["ps"] = "source-b"
        two = "vmess://" + base64.b64encode(__import__("json").dumps(base).encode()).decode()
        self.assertEqual(normalize_key(one), normalize_key(two))

    def test_default_subscription_is_always_first(self) -> None:
        rows = normalize_subscription_urls(["https://example.com/sub", "bad", DEFAULT_SUBSCRIPTION_URL])
        self.assertEqual(rows[0], DEFAULT_SUBSCRIPTION_URL)
        self.assertEqual(rows.count(DEFAULT_SUBSCRIPTION_URL), 1)
        self.assertIn("https://example.com/sub", rows)
        self.assertNotIn("bad", rows)

    def test_wintun_is_extracted_next_to_xray(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            core = root / "core"
            core.mkdir()
            executable = core / "xray.exe"
            executable.write_bytes(b"xray")
            payload = b"w" * 60000
            archive_bytes = root / "source.zip"
            with zipfile.ZipFile(archive_bytes, "w") as package:
                package.writestr("wintun/bin/amd64/wintun.dll", payload)
            digest = hashlib.sha256(archive_bytes.read_bytes()).hexdigest()

            def fake_download(_url, target, timeout=90):
                target.write_bytes(archive_bytes.read_bytes())

            with patch("dicodeping.xray.is_windows", return_value=True), \
                 patch("dicodeping.xray.CORE_DIR", core), \
                 patch("dicodeping.xray.BUNDLED_CORE_DIR", root / "bundle"), \
                 patch("dicodeping.xray.APP_ROOT", root / "app"), \
                 patch("dicodeping.xray.WINTUN_SHA256", digest), \
                 patch("dicodeping.xray._wintun_arch_folder", return_value="amd64"), \
                 patch("dicodeping.xray._download_file", side_effect=fake_download):
                result = ensure_wintun(executable)
            self.assertEqual(result, core / "wintun.dll")
            self.assertEqual(result.read_bytes(), payload)

    def test_source_order_and_default_are_preserved(self) -> None:
        settings = {
            "sources": [
                {"id": "x", "name": "Second", "url": "https://example.com/sub", "order": 0, "enabled": True},
                {"id": "default", "name": "Main renamed", "url": DEFAULT_SUBSCRIPTION_URL, "order": 1, "enabled": True, "is_default": True},
            ]
        }
        rows = normalize_sources(settings, "en")
        self.assertEqual([item.name for item in rows], ["Second", "Main renamed"])
        self.assertEqual(rows[1].id, "default")
        self.assertTrue(rows[1].enabled)
        self.assertEqual(len(serialize_sources(rows)), 2)

    def test_manual_servers_are_kept_when_icmp_is_blocked(self) -> None:
        raw = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls#manual"
        store = FakeStore()
        service = ServerService(store)
        service.geo = FakeGeo()
        entry = DiscoveredConfig(raw, "source-a", "Source A", 3)
        with patch("dicodeping.service.ping_many", return_value=[PingResult("example.com", None, "1.2.3.4")]):
            records = service.build_and_save([entry], language="en")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, "unverified")
        self.assertEqual(records[0].source_id, "source-a")
        self.assertEqual(records[0].source_name, "Source A")
        self.assertIsNone(records[0].ping_ms)

    def test_service_saves_alive_configs_without_source_label(self) -> None:
        raw_one = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls#source-channel"
        raw_two = "trojan://password@example.com:443?security=tls#another-source"
        store = FakeStore()
        service = ServerService(store)
        service.geo = FakeGeo()
        with patch("dicodeping.service.ping_many", return_value=[PingResult("example.com", 85, "1.2.3.4")]):
            records = service.build_and_save([raw_one, raw_two])
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record.ping_ms == 85 for record in records))
        decoded = [blob_to_config(record.config_blob) for record in records]
        self.assertTrue(all("source-channel" not in item and "another-source" not in item for item in decoded))


if __name__ == "__main__":
    unittest.main()
