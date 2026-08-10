from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class Endpoint:
    raw: str
    protocol: str
    host: str
    port: int


@dataclass(slots=True)
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


@dataclass(slots=True)
class ServerRecord:
    id: str
    name: str
    protocol: str
    host: str
    port: int
    config_blob: str
    core_profile_id: str = ""
    network: str = ""
    transport_security: str = ""
    ping_ms: int | None = None
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
            name=str(data.get("name") or "Server"),
            protocol=str(data.get("protocol") or "UNKNOWN"),
            host=str(data.get("host") or ""),
            port=int(data.get("port") or 0),
            config_blob=str(data.get("config_blob") or ""),
            core_profile_id=str(data.get("core_profile_id") or ""),
            network=str(data.get("network") or ""),
            transport_security=str(data.get("transport_security") or ""),
            ping_ms=int(data["ping_ms"]) if data.get("ping_ms") is not None else None,
            source_id=str(data.get("source_id") or "default"),
            source_name=str(data.get("source_name") or "منبع اصلی"),
            source_order=int(data.get("source_order") or 0),
            status=str(data.get("status") or "unknown"),
            favorite=bool(data.get("favorite", False)),
            last_checked=str(data.get("last_checked") or ""),
            last_connected=str(data.get("last_connected") or ""),
            failures=int(data.get("failures") or 0),
        )
