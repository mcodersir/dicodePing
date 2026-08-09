"""v2rayN-based data models for dicodePing Version 3.

Defines the core data structures used throughout the
v2rayN integration layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Endpoint:
    raw: str
    protocol: str
    host: str
    port: int


@dataclass
class SourceDefinition:
    id: str
    name: str
    url: str
    order: int = 0
    enabled: bool = True
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "order": self.order,
            "enabled": self.enabled,
            "is_default": self.is_default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceDefinition":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            url=str(data.get("url") or ""),
            order=int(data.get("order") or 0),
            enabled=bool(data.get("enabled", True)),
            is_default=bool(data.get("is_default", False)),
        )


@dataclass
class DiscoveredConfig:
    raw: str
    source_id: str
    source_name: str
    source_order: int = 0


@dataclass
class ServerRecord:
    id: str
    name: str
    protocol: str
    host: str
    port: int
    config_blob: str
    tcp_ms: int | None = None
    ping_ms: int | None = None
    icmp_ms: int | None = None
    ip: str = ""
    country: str = "نامشخص"
    country_code: str = ""
    region: str = ""
    city: str = ""
    isp: str = ""
    asn: str = ""
    geo_provider: str = ""
    geo_confidence: str = ""
    source_id: str = "default"
    source_name: str = "منبع اصلی"
    source_order: int = 0
    status: str = "unknown"
    favorite: bool = False
    last_checked: str = ""
    last_connected: str = ""
    failures: int = 0
    profile_tag: str = "unknown"
    security_score: int = 0
    security_level: str = "unknown"
    security_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "config_blob": self.config_blob,
            "tcp_ms": self.tcp_ms,
            "ping_ms": self.ping_ms,
            "icmp_ms": self.icmp_ms,
            "ip": self.ip,
            "country": self.country,
            "country_code": self.country_code,
            "region": self.region,
            "city": self.city,
            "isp": self.isp,
            "asn": self.asn,
            "geo_provider": self.geo_provider,
            "geo_confidence": self.geo_confidence,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_order": self.source_order,
            "status": self.status,
            "favorite": self.favorite,
            "last_checked": self.last_checked,
            "last_connected": self.last_connected,
            "failures": self.failures,
            "profile_tag": self.profile_tag,
            "security_score": self.security_score,
            "security_level": self.security_level,
            "security_summary": self.security_summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerRecord":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or "سرور"),
            protocol=str(data.get("protocol") or "UNKNOWN"),
            host=str(data.get("host") or ""),
            port=int(data.get("port") or 0),
            config_blob=str(data.get("config_blob") or ""),
            tcp_ms=int(data["tcp_ms"]) if data.get("tcp_ms") is not None else (
                int(data["icmp_ms"]) if data.get("icmp_ms") is not None else None
            ),
            ping_ms=int(data["ping_ms"]) if data.get("ping_ms") is not None else None,
            icmp_ms=int(data["icmp_ms"]) if data.get("icmp_ms") is not None else None,
            ip=str(data.get("ip") or ""),
            country=str(data.get("country") or "نامشخص"),
            country_code=str(data.get("country_code") or ""),
            region=str(data.get("region") or ""),
            city=str(data.get("city") or ""),
            isp=str(data.get("isp") or ""),
            asn=str(data.get("asn") or ""),
            geo_provider=str(data.get("geo_provider") or ""),
            geo_confidence=str(data.get("geo_confidence") or ""),
            source_id=str(data.get("source_id") or "default"),
            source_name=str(data.get("source_name") or "منبع اصلی"),
            source_order=int(data.get("source_order") or 0),
            status=str(data.get("status") or "unknown"),
            favorite=bool(data.get("favorite", False)),
            last_checked=str(data.get("last_checked") or ""),
            last_connected=str(data.get("last_connected") or ""),
            failures=int(data.get("failures") or 0),
            profile_tag=str(data.get("profile_tag") or "unknown"),
            security_score=int(data.get("security_score") or 0),
            security_level=str(data.get("security_level") or "unknown"),
            security_summary=str(data.get("security_summary") or ""),
        )
