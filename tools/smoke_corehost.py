from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PREFIX = "@dicodeping:"


def read_frame(proc: subprocess.Popen[str], *, expected_id: str | None = None) -> dict:
    assert proc.stdout is not None
    for _ in range(200):
        line = proc.stdout.readline()
        if not line:
            break
        if not line.startswith(PREFIX):
            continue
        payload = json.loads(line[len(PREFIX):])
        if expected_id is None or payload.get("id") == expected_id:
            return payload
    stderr = proc.stderr.read() if proc.stderr else ""
    raise RuntimeError(f"CoreHost did not emit expected frame. stderr={stderr[-2000:]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", type=Path)
    args = parser.parse_args()
    engine = args.engine.resolve()
    host = engine / ("dicodePing.CoreHost.exe" if os.name == "nt" else "dicodePing.CoreHost")
    if not host.is_file():
        raise SystemExit(f"CoreHost missing: {host}")
    proc = subprocess.Popen(
        [str(host)], cwd=engine, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        ready = read_frame(proc)
        if not ready.get("ok") or ready.get("type") != "ready":
            raise RuntimeError(f"CoreHost initialization failed: {ready}")
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"id": "hello", "op": "hello", "args": {}}) + "\n")
        proc.stdin.flush()
        hello = read_frame(proc, expected_id="hello")
        if not hello.get("ok") or hello.get("result", {}).get("product") != "dicodePing":
            raise RuntimeError(f"hello failed: {hello}")
        proc.stdin.write(json.dumps({"id": "stop", "op": "shutdown", "args": {}}) + "\n")
        proc.stdin.flush()
        stopped = read_frame(proc, expected_id="stop")
        if not stopped.get("ok"):
            raise RuntimeError(f"shutdown failed: {stopped}")
        return proc.wait(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
