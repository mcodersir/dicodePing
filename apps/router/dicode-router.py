#!/usr/bin/env python3
"""Run DicodePing Fox as an authenticated LAN proxy."""
import fcntl
import getpass
import json
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading

DATA = Path("/data")
STATE = DATA / "fox-state.json"
SETTINGS = DATA / "gateway.json"
STOP = threading.Event()


def write_private(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def call_fox(operation, **fields):
    result = subprocess.run(
        ["dicode-fox"], input=json.dumps({"operation": operation, **fields}) + "\n",
        capture_output=True, text=True, timeout=180, check=False,
    )
    reply = json.loads(result.stdout.splitlines()[-1]) if result.stdout.strip() else {}
    if not reply.get("ok"):
        raise RuntimeError(f"Fox request failed ({reply.get('error', 'no_response')})")
    return reply


def login():
    email = input("Firefox Account email: ").strip()
    country = input("Country code (Enter for recommended): ").strip().upper() or "REC"
    if country != "REC" and not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("Enter a two-letter country code.")
    response = call_fox("login", email=email, password=getpass.getpass("Firefox Account password: "))
    if response.get("needs_verification"):
        response = call_fox("verify", state=response["state"], code=getpass.getpass("Verification code: "))
    if not response.get("state", {}).get("access_token"):
        raise RuntimeError("Firefox Account sign-in did not return a usable session.")
    proxy_user = input("LAN proxy username: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", proxy_user):
        raise ValueError("Use 1–64 letters, digits, dots, underscores or hyphens.")
    password = getpass.getpass("LAN proxy password (Enter to generate): ")
    generated = not password
    if generated:
        password = secrets.token_urlsafe(24)
    if len(password.encode()) < 16 or len(password.encode()) > 128:
        raise ValueError("Use a LAN proxy password between 16 and 128 bytes.")
    with (DATA / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        write_private(STATE, response["state"])
        write_private(SETTINGS, {"user": proxy_user, "password": password, "country": country,
                                 "generation": secrets.token_hex(16)})
    if generated:
        print(f"Generated LAN proxy password, store privately: {password}")
    print("LAN proxy credentials saved.")


def stop_process(child):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=4)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def read_replies(stream, replies):
    for line in stream:
        try:
            replies.put(json.loads(line))
        except ValueError:
            continue
    replies.put(None)


def gateway_session():
    with (DATA / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            settings = json.loads(SETTINGS.read_text())
            state = json.loads(STATE.read_text())
        except FileNotFoundError:
            return
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)

        fox = subprocess.Popen(
            ["dicode-fox"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True,
        )
        proxy = None
        try:
            fox.stdin.write(json.dumps({
                "operation": "serve", "state": state, "country": settings["country"],
                "config_cache": str(DATA / "foxy-cache.json"), "listen": "127.0.0.1:10809",
            }) + "\n")
            fox.stdin.flush()
            replies = queue.Queue()
            threading.Thread(target=read_replies, args=(fox.stdout, replies), daemon=True).start()
            with tempfile.TemporaryDirectory() as temporary:
                config = Path(temporary) / "proxy.json"
                while not STOP.is_set() and (proxy is None or proxy.poll() is None):
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    current = json.loads(SETTINGS.read_text())
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    if current["generation"] != settings["generation"]:
                        break
                    try:
                        reply = replies.get(timeout=0.8)
                    except queue.Empty:
                        continue
                    if not reply or not reply.get("ok"):
                        break
                    if reply.get("state"):
                        fcntl.flock(lock, fcntl.LOCK_EX)
                        if json.loads(SETTINGS.read_text())["generation"] == settings["generation"]:
                            write_private(STATE, reply["state"])
                        fcntl.flock(lock, fcntl.LOCK_UN)
                    if reply.get("event") != "ready" or proxy is not None:
                        continue
                    write_private(config, {
                        "log": {"level": "warn"},
                        "inbounds": [{"type": "mixed", "listen": "0.0.0.0", "listen_port": 10810,
                                      "users": [{"username": settings["user"], "password": settings["password"]}]}],
                        "outbounds": [{"type": "socks", "tag": "fox", "server": "127.0.0.1",
                                       "server_port": 10809, "version": "5", "network": "tcp"}],
                        "route": {"final": "fox"},
                    })
                    proxy = subprocess.Popen(["sing-box", "run", "-c", str(config)])
                    print("Authenticated proxy started on TCP port 10810.", flush=True)
        finally:
            stop_process(proxy)
            stop_process(fox)
            fox.stdin.close()
            fox.stdout.close()


def main():
    os.umask(0o077)
    DATA.mkdir(exist_ok=True)
    if sys.argv[1:] == ["login"]:
        login()
        return
    if sys.argv[1:] != ["run"]:
        raise SystemExit("Usage: dicode-router run | login")
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: STOP.set())
    while not STOP.is_set():
        try:
            gateway_session()
        except (OSError, ValueError, KeyError):
            print("Gateway is waiting for a valid configuration or connection.", flush=True)
        STOP.wait(5)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as failure:
        sys.exit(str(failure) if isinstance(failure, (RuntimeError, ValueError)) else "Gateway setup failed.")
