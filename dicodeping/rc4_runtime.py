from __future__ import annotations

import concurrent.futures
import socket
import time

from PySide6.QtCore import Qt

from . import net as net_module
from . import service as service_module
from .protocols import blob_to_config, parse_endpoint
from .rc2_core import extract_display_name
from .rc3_core import median_latency, trusted_latency
from .rc4_core import preferred_display_name, usable_for_auto

_PATCHED = False


def _tcp_samples(ip: str, port: int, attempts: int = 2, timeout: float = 0.9) -> list[int]:
    values: list[int] = []
    for _ in range(max(1, attempts)):
        started = time.perf_counter()
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                values.append(max(1, int(round((time.perf_counter() - started) * 1000))))
        except OSError:
            pass
    return values


def _probe_endpoint(host: str, port: int) -> tuple[int | None, str]:
    """Fast, real TCP handshake probe for one unique endpoint."""
    addresses = net_module.resolve_all_ipv4(host)[:2]
    choices: list[tuple[int, str]] = []
    for ip in addresses:
        latency = median_latency(_tcp_samples(ip, port))
        if latency is not None:
            choices.append((latency, ip))
    if not choices:
        return None, addresses[0] if addresses else "dns"
    return min(choices, key=lambda item: item[0])


def _repair_names(records) -> None:
    for server in records:
        try:
            raw = blob_to_config(server.config_blob)
        except Exception:
            raw = ""
        explicit = extract_display_name(raw)
        fallback = f"{server.protocol or 'Xray'} • {server.host}:{server.port}"
        name = preferred_display_name(explicit, fallback)
        if name:
            server.name = name


def _install_service_patch() -> None:
    def refresh(self, *args, **kwargs):
        records = self.store.load_servers()
        by_endpoint: dict[tuple[str, int], list] = {}
        for server in records:
            if server.host:
                by_endpoint.setdefault((server.host, int(server.port or 443)), []).append(server)

        endpoints = list(by_endpoint)
        callback = kwargs.get("ping_progress") or kwargs.get("progress")
        results: dict[tuple[str, int], tuple[int | None, str]] = {}
        done = 0
        # Deduplicating endpoints removes repeated DNS/TCP work from subscriptions
        # that expose the same relay under several display names.
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(64, len(endpoints) or 1))) as pool:
            futures = {pool.submit(_probe_endpoint, host, port): (host, port) for host, port in endpoints}
            for future in concurrent.futures.as_completed(futures):
                endpoint = futures[future]
                try:
                    results[endpoint] = future.result()
                except Exception:
                    results[endpoint] = (None, "")
                done += 1
                if callback:
                    callback(done, len(endpoints))

        for endpoint, servers in by_endpoint.items():
            ping_ms, ip = results.get(endpoint, (None, ""))
            for server in servers:
                server.last_checked = service_module.utc_now()
                if ip:
                    server.ip = ip
                if trusted_latency(ping_ms):
                    server.ping_ms = ping_ms
                    server.status = "online"
                    server.failures = 0
                else:
                    server.ping_ms = None
                    server.status = "unverified"
                    server.failures += 1

        # Geo is presentation metadata. It must never block auto-connect and is
        # requested once per unique resolved IP.
        ips = list(dict.fromkeys(server.ip for server in records if server.ip and server.ip != "dns"))
        geo = self.geo.resolve_many(ips, callback=kwargs.get("geo_progress"))
        for server in records:
            row = geo.get(server.ip, {})
            if row:
                for field in ("country", "country_code", "region", "city", "isp", "asn", "geo_provider", "geo_confidence"):
                    value = row.get(field)
                    if value:
                        setattr(server, field, str(value).upper() if field == "country_code" else str(value))
        _repair_names(records)
        records.sort(key=service_module._sort_key)
        self.store.save_servers(records)
        return records

    service_module.ServerService.refresh_saved = refresh
    service_module._is_auto_candidate = lambda server: usable_for_auto(server.status, server.ping_ms)


def _install_ui_patch() -> None:
    from .ui import MainWindow, country_flag_pixmap

    original_render = MainWindow._render_home_summary

    def selection(self):
        # Selecting is informational. It must not silently disable automatic
        # connection; explicit Connect actions still switch to manual mode.
        self._update_manual_connect_state()
        if self._restoring_server_selection:
            return
        server = self.selected_server()
        if not server:
            return
        self.settings["selected_server_id"] = server.id
        self.store.save_settings(self.settings)
        self._render_home_summary()

    def render(self):
        original_render(self)
        if self.connected_id:
            return
        selected = self.selected_server()
        if not selected:
            return
        self.home_target_label.setText(self.t("selected_connection_server"))
        self.home_best_flag.setPixmap(country_flag_pixmap(selected.country_code, 38, 26))
        self.home_best_flag.setToolTip(selected.country or self.t("unknown"))
        self.home_best_flag.setVisible(True)
        self.home_best_name.setText(selected.name)
        latency = f"{selected.ping_ms} ms" if selected.ping_ms is not None else self.t("icmp_unavailable")
        self.home_best_meta.setText(
            f"{self._server_location_text(selected, include_country=False)}  •  {selected.ip or selected.host}  •  {latency}"
        )

    MainWindow._server_selection_changed = selection
    MainWindow._render_home_summary = render


def install_rc4_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _install_service_patch()
    _install_ui_patch()
