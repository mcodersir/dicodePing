from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .constants import GEO_CACHE_FILE, SERVERS_FILE, SETTINGS_FILE
from .models import ServerRecord


class JsonStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    @staticmethod
    def _read(path: Path, fallback: Any) -> Any:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return fallback

    @staticmethod
    def _write(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def load_servers(self) -> list[ServerRecord]:
        with self._lock:
            rows = self._read(SERVERS_FILE, [])
            result: list[ServerRecord] = []
            for row in rows if isinstance(rows, list) else []:
                try:
                    result.append(ServerRecord.from_dict(row))
                except Exception:
                    continue
            return result

    def save_servers(self, servers: list[ServerRecord]) -> None:
        with self._lock:
            self._write(SERVERS_FILE, [server.to_dict() for server in servers])

    def load_settings(self) -> dict[str, Any]:
        with self._lock:
            value = self._read(SETTINGS_FILE, {})
            return value if isinstance(value, dict) else {}

    def save_settings(self, settings: dict[str, Any]) -> None:
        with self._lock:
            self._write(SETTINGS_FILE, settings)

    def load_geo_cache(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            value = self._read(GEO_CACHE_FILE, {})
            return value if isinstance(value, dict) else {}

    def save_geo_cache(self, cache: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            self._write(GEO_CACHE_FILE, cache)
