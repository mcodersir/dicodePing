"""Lifecycle primitives shared by every dicodePing connection core.

The registry owns only processes started by this application.  A generation
token makes late callbacks from a cancelled start harmless and the port
registry prevents scanner workers and long-lived cores from racing for the
same loopback listener.
"""
from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterator


class CoreState(StrEnum):
    NOT_INSTALLED = "notInstalled"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLING = "installing"
    INSTALLED = "installed"
    STARTING = "starting"
    VALIDATING = "validating"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    UNSUPPORTED = "unsupportedInThisBuild"
    MISSING_AUTHORIZED_CONFIG = "missingAuthorizedConfig"


@dataclass(slots=True)
class TrafficStats:
    bytes_sent: int | None = None
    bytes_received: int | None = None

    @property
    def supported(self) -> bool:
        return self.bytes_sent is not None and self.bytes_received is not None


@dataclass(slots=True)
class RuntimeStatus:
    state: CoreState = CoreState.DISCONNECTED
    generation: int = 0
    last_error: str = ""
    last_successful_validation: float | None = None
    traffic: TrafficStats = field(default_factory=TrafficStats)


class CancellationToken:
    def __init__(self, generation: int) -> None:
        self.generation = generation
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise RuntimeError("operation cancelled")


class ProcessRegistry:
    """Thread-safe ownership and teardown of application child processes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: dict[int, subprocess.Popen] = {}
        atexit.register(self.stop_all)

    def register(self, process: subprocess.Popen) -> subprocess.Popen:
        with self._lock:
            self._processes[process.pid] = process
        return process

    def forget(self, process: subprocess.Popen | None) -> None:
        if process is None:
            return
        with self._lock:
            self._processes.pop(process.pid, None)

    def stop(self, process: subprocess.Popen | None, timeout: float = 3.0) -> None:
        if process is None:
            return
        try:
            if process.poll() is None:
                if os.name == "nt":
                    process.terminate()
                else:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    except (OSError, ProcessLookupError):
                        process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            capture_output=True,
                            timeout=5,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                    else:
                        try:
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        except (OSError, ProcessLookupError):
                            process.kill()
                    process.wait(timeout=2)
            else:
                process.wait(timeout=0.2)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            self.forget(process)

    def stop_all(self) -> None:
        with self._lock:
            owned = list(self._processes.values())
        for process in owned:
            self.stop(process, timeout=1.5)

    def alive_count(self) -> int:
        with self._lock:
            dead = [pid for pid, proc in self._processes.items() if proc.poll() is not None]
            for pid in dead:
                self._processes.pop(pid, None)
            return len(self._processes)


class PortRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._reserved: set[int] = set()

    def acquire(self, preferred: int | None = None) -> int:
        with self._lock:
            if preferred:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    try:
                        sock.bind(("127.0.0.1", int(preferred)))
                    except OSError:
                        pass
                    else:
                        if int(preferred) not in self._reserved:
                            self._reserved.add(int(preferred))
                            return int(preferred)
            for _ in range(64):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = int(sock.getsockname()[1])
                if port not in self._reserved:
                    self._reserved.add(port)
                    return port
        raise RuntimeError("unable to reserve a unique local port")

    def release(self, port: int) -> None:
        with self._lock:
            self._reserved.discard(int(port))

    @contextmanager
    def reservation(self) -> Iterator[int]:
        port = self.acquire()
        try:
            yield port
        finally:
            self.release(port)


PROCESS_REGISTRY = ProcessRegistry()
PORT_REGISTRY = PortRegistry()


class LifecycleController:
    """Serialized Start/Stop/Switch controller with generation cancellation."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.status = RuntimeStatus()
        self._token = CancellationToken(0)
        self._operation_thread: threading.Thread | None = None

    def begin(self, state: CoreState) -> CancellationToken:
        with self.lock:
            self._token.cancel()
            previous = self._operation_thread
            if previous and previous is not threading.current_thread() and previous.is_alive():
                previous.join(timeout=3)
            self.status.generation += 1
            self._token = CancellationToken(self.status.generation)
            self._operation_thread = threading.current_thread()
            self.status.state = state
            self.status.last_error = ""
            return self._token

    def cancel(self) -> None:
        with self.lock:
            self._token.cancel()

    def transition(self, token: CancellationToken, state: CoreState) -> bool:
        with self.lock:
            if token.generation != self.status.generation or token.is_cancelled():
                return False
            self.status.state = state
            if state == CoreState.CONNECTED:
                self.status.last_successful_validation = time.time()
            return True

    def fail(self, token: CancellationToken, error: BaseException | str) -> None:
        with self.lock:
            if token.generation != self.status.generation:
                return
            self.status.state = CoreState.FAILED
            self.status.last_error = str(error)
