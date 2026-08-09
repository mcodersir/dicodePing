from __future__ import annotations

import json
import os
import shutil
import tempfile
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

    def save_scanner_transaction(
        self,
        *,
        settings: dict[str, Any],
        servers: list[ServerRecord],
        history_path: Path,
        history: list[dict[str, Any]],
        raw_path: Path,
        raw_payload: str,
        base64_path: Path,
        base64_payload: str,
    ) -> None:
        """Validate, stage and commit the complete scanner result as one unit.

        Cross-file replacement is protected by backups and immediate rollback.
        A crash-safe marker is retained only while replacement is in progress;
        no source metadata is published before all staged payloads validate.
        """
        with self._lock:
            targets: list[tuple[Path, str]] = [
                (SETTINGS_FILE, json.dumps(settings, ensure_ascii=False, indent=2)),
                (SERVERS_FILE, json.dumps([item.to_dict() for item in servers], ensure_ascii=False, indent=2)),
                (history_path, json.dumps(history, ensure_ascii=False, indent=2)),
                (raw_path, raw_payload),
                (base64_path, base64_payload),
            ]
            for path, payload in targets:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix == ".json":
                    json.loads(payload)
            # Verify model integrity before touching any live file.
            for item in servers:
                ServerRecord.from_dict(item.to_dict())

            staging = Path(tempfile.mkdtemp(prefix=".scanner-txn-", dir=str(SETTINGS_FILE.parent)))
            backups = staging / "backups"
            backups.mkdir()
            marker = staging / "transaction.json"
            staged: list[tuple[Path, Path, Path | None]] = []
            committed: list[tuple[Path, Path | None]] = []
            try:
                for index, (target, payload) in enumerate(targets):
                    candidate = staging / f"{index:02d}-{target.name}"
                    candidate.write_text(payload, encoding="utf-8")
                    if target.suffix == ".json":
                        json.loads(candidate.read_text(encoding="utf-8"))
                    backup = backups / f"{index:02d}-{target.name}" if target.exists() else None
                    staged.append((candidate, target, backup))
                marker.write_text(
                    json.dumps({"targets": [str(target) for _, target, _ in staged]}),
                    encoding="utf-8",
                )
                for candidate, target, backup in staged:
                    if backup is not None:
                        shutil.copy2(target, backup)
                    os.replace(candidate, target)
                    committed.append((target, backup))
                marker.unlink(missing_ok=True)
            except Exception:
                for target, backup in reversed(committed):
                    try:
                        if backup is None:
                            target.unlink(missing_ok=True)
                        else:
                            os.replace(backup, target)
                    except OSError:
                        pass
                raise
            finally:
                shutil.rmtree(staging, ignore_errors=True)
