from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
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
        return asdict(self)

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
    ping_ms: int | None = None
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerRecord":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or "سرور"),
            protocol=str(data.get("protocol") or "UNKNOWN"),
            host=str(data.get("host") or ""),
            port=int(data.get("port") or 0),
            config_blob=str(data.get("config_blob") or ""),
            ping_ms=int(data["ping_ms"]) if data.get("ping_ms") is not None else None,
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
        )
