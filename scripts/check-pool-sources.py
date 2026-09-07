"""Capture public Telegram HTML for the production parser smoke tests in release CI.

Only HTML is fetched: candidate configurations are never executed by this script.
The bounded fixtures are ephemeral and are not included in release artifacts.
"""
import concurrent.futures
import pathlib
import sys
import urllib.request


def capture(channel):
    request = urllib.request.Request(
        "https://t.me/s/" + channel,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/128 Safari/537.36 DicodePing/4.0.0",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8,fa;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("response too large")
        (destination / (channel + ".html")).write_bytes(content)
        print(channel, "captured", len(content), "bytes", flush=True)
        return True
    except Exception as error:
        print(channel, type(error).__name__, flush=True)
        return False


destination = pathlib.Path(sys.argv[1]).resolve()
destination.mkdir(parents=True, exist_ok=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    captured = list(pool.map(capture, ["CucumberNet", "V2RayRootFree", "V2rayNGX", "fnet00", "configmahsa"]))
if not any(captured):
    raise SystemExit("No public Telegram response available for release smoke tests")
