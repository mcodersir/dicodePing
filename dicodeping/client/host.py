from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from dicodeping.constants import BUNDLE_ROOT, DATA_DIR, VERSION

_PREFIX = "@dicodeping:"


class CoreHostError(RuntimeError):
    pass


class CoreHostUnavailable(CoreHostError):
    pass


class CoreHostClient:
    """RPC boundary to the native desktop networking runtime.

    The UI/business layer never manages proxy processes directly.  This object
    starts one dicodePing CoreHost process, sends newline-delimited JSON
    requests and receives framed JSON replies.  The host owns profile parsing,
    core generation/lifecycle, system proxy, TUN, DNS/routing and real latency.
    """

    def __init__(self, *, startup_timeout: float = 15.0) -> None:
        self.startup_timeout = startup_timeout
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._responses: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._responses_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._ready = threading.Event()
        self._closed = False
        self._fatal_error: str | None = None
        self._stderr_tail: list[str] = []

    @staticmethod
    def _host_name() -> str:
        return "dicodePing.CoreHost.exe" if os.name == "nt" else "dicodePing.CoreHost"

    @staticmethod
    def _runtime_dir() -> Path:
        return DATA_DIR / "engine" / VERSION

    @classmethod
    def _bundled_engine_dir(cls) -> Path:
        override = os.environ.get("DICODEPING_ENGINE_DIR", "").strip()
        if override:
            return Path(override).expanduser().resolve()
        return BUNDLE_ROOT / "engine"

    @classmethod
    def _development_host(cls) -> Path | None:
        override = os.environ.get("DICODEPING_CORE_HOST", "").strip()
        if override:
            path = Path(override).expanduser().resolve()
            return path if path.exists() else None
        root = Path(__file__).resolve().parents[2]
        candidates = list(root.glob(f"corehost/bin/**/publish/{cls._host_name()}"))
        return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

    @classmethod
    def _ensure_runtime(cls) -> Path:
        bundled = cls._bundled_engine_dir()
        dev_host = cls._development_host()
        if dev_host and not bundled.exists():
            return dev_host

        source_host = bundled / cls._host_name()
        if not source_host.exists():
            if dev_host:
                return dev_host
            raise CoreHostUnavailable(
                "Desktop runtime is not packaged. Build the CoreHost for this platform first."
            )

        target_dir = cls._runtime_dir()
        target_host = target_dir / cls._host_name()
        marker = target_dir / ".runtime-version"
        expected_marker = f"{VERSION}\n"
        needs_copy = not target_host.exists()
        try:
            needs_copy = needs_copy or marker.read_text(encoding="utf-8") != expected_marker
        except OSError:
            needs_copy = True
        if needs_copy:
            temp = target_dir.with_name(target_dir.name + ".new")
            shutil.rmtree(temp, ignore_errors=True)
            temp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundled, temp)
            (temp / ".runtime-version").write_text(expected_marker, encoding="utf-8")
            shutil.rmtree(target_dir, ignore_errors=True)
            temp.replace(target_dir)
        if os.name != "nt":
            try:
                target_host.chmod(target_host.stat().st_mode | 0o111)
                for child in (target_dir / "bin").rglob("*") if (target_dir / "bin").exists() else ():
                    if child.is_file() and child.suffix not in {".json", ".dat", ".db"}:
                        child.chmod(child.stat().st_mode | 0o111)
            except OSError:
                pass
        return target_host

    @property
    def running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None and self._ready.is_set())

    @property
    def stderr_tail(self) -> list[str]:
        return list(self._stderr_tail[-80:])

    def start(self) -> None:
        if self.running:
            return
        if self._closed:
            raise CoreHostError("CoreHost client is closed")
        host = self._ensure_runtime()
        self._ready.clear()
        self._fatal_error = None
        try:
            self._proc = subprocess.Popen(
                [str(host)],
                cwd=str(host.parent),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        except OSError as exc:
            raise CoreHostUnavailable(f"Could not start desktop runtime: {exc}") from exc
        self._reader = threading.Thread(target=self._read_stdout, name="corehost-stdout", daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, name="corehost-stderr", daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        if not self._ready.wait(self.startup_timeout):
            tail = "\n".join(self.stderr_tail[-8:])
            self.close(force=True)
            raise CoreHostUnavailable(f"Desktop runtime did not initialize.\n{tail}".strip())
        if self._fatal_error or not self._proc or self._proc.poll() is not None:
            detail = self._fatal_error or "Desktop runtime exited during initialization"
            self.close(force=True)
            raise CoreHostUnavailable(detail)

    def _read_stdout(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for raw in proc.stdout:
            line = raw.strip()
            if not line.startswith(_PREFIX):
                continue
            try:
                payload = json.loads(line[len(_PREFIX):])
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "ready" and payload.get("ok"):
                self._ready.set()
                continue
            if payload.get("type") == "fatal":
                self._fatal_error = str(payload.get("error") or "runtime fatal error")
                self._stderr_tail.append(self._fatal_error)
                self._ready.set()
                self._fail_pending(self._fatal_error)
                continue
            request_id = str(payload.get("id") or "")
            with self._responses_lock:
                target = self._responses.get(request_id)
            if target:
                target.put(payload)
        self._ready.set()
        if not self._closed:
            self._fail_pending("Desktop runtime exited unexpectedly")

    def _fail_pending(self, message: str) -> None:
        with self._responses_lock:
            pending = list(self._responses.values())
        for inbox in pending:
            try:
                inbox.put_nowait({"ok": False, "error": message})
            except queue.Full:
                pass

    def _read_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for raw in proc.stderr:
            line = raw.rstrip()
            if line:
                self._stderr_tail.append(line)
                del self._stderr_tail[:-200]

    def request(self, op: str, args: dict[str, Any] | None = None, *, timeout: float = 45.0) -> dict[str, Any]:
        self.start()
        proc = self._proc
        if not proc or not proc.stdin or proc.poll() is not None:
            raise CoreHostUnavailable("Desktop runtime is not running")
        request_id = uuid.uuid4().hex
        inbox: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._responses_lock:
            self._responses[request_id] = inbox
        try:
            message = json.dumps({"id": request_id, "op": op, "args": args or {}}, ensure_ascii=False)
            with self._write_lock:
                proc.stdin.write(message + "\n")
                proc.stdin.flush()
            try:
                response = inbox.get(timeout=timeout)
            except queue.Empty as exc:
                if proc.poll() is not None:
                    detail = "\n".join(self.stderr_tail[-8:])
                    raise CoreHostUnavailable(f"Desktop runtime exited unexpectedly.\n{detail}".strip()) from exc
                raise CoreHostError(f"Runtime operation timed out: {op}") from exc
            if not response.get("ok"):
                raise CoreHostError(str(response.get("error") or f"Runtime operation failed: {op}"))
            result = response.get("result")
            return result if isinstance(result, dict) else {"value": result}
        finally:
            with self._responses_lock:
                self._responses.pop(request_id, None)

    def sync_source(self, source_id: str, content: str) -> list[dict[str, Any]]:
        return list(self.request("sync_source", {"source_id": source_id, "content": content}, timeout=90).get("profiles", []))

    def connect(self, profile_id: str, *, tun: bool = False, system_proxy: str = "on") -> dict[str, Any]:
        return self.request("connect", {"profile_id": profile_id, "tun": tun, "system_proxy": system_proxy}, timeout=35)

    def disconnect(self) -> dict[str, Any]:
        return self.request("disconnect", timeout=20)

    def status(self) -> dict[str, Any]:
        return self.request("status", timeout=5)

    def latency(self, profile_ids: list[str]) -> dict[str, int | None]:
        # Real probes are bounded and concurrent, but a large subscription can
        # still need several waves. Keep the RPC deadline above the CoreHost
        # estimate so the UI does not report a false timeout for the tail.
        # CoreHost bounds real probes to 24 workers.  Keep this estimate in
        # lockstep so the desktop UI never times out a valid parallel batch.
        workers = 24
        waves = max(1, (len(profile_ids) + workers - 1) // workers)
        timeout = min(900, max(150, 30 + waves * 12))
        result = self.request("latency", {"profile_ids": profile_ids}, timeout=timeout)
        rows = result.get("results", {})
        return {str(k): (int(v) if v is not None else None) for k, v in rows.items()} if isinstance(rows, dict) else {}

    def probe_payload(self, content: str) -> list[dict[str, Any]]:
        rows = self.request("probe_payload", {"content": content}, timeout=140).get("profiles", [])
        return [row for row in rows if isinstance(row, dict)]

    def stats(self) -> dict[str, Any]:
        return self.request("stats", timeout=5)

    def logs(self, limit: int = 200) -> list[str]:
        return [str(x) for x in self.request("logs", {"limit": limit}, timeout=5).get("lines", [])]

    def settings_get(self) -> dict[str, Any]:
        return self.request("settings_get", timeout=5)

    def settings_set(self, **settings: Any) -> dict[str, Any]:
        return self.request("settings_set", settings, timeout=8)

    def close(self, *, force: bool = False) -> None:
        proc = self._proc
        if not proc:
            self._closed = True
            return
        if proc.poll() is None and not force:
            try:
                self.request("shutdown", timeout=6)
            except Exception:
                pass
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._closed = True

    def __enter__(self) -> "CoreHostClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
