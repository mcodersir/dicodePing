from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "vazirmatn"
VERSION = "33.0.3"
REGISTRY = f"https://registry.npmjs.org/{PACKAGE}/{VERSION}"
WEIGHTS = ("Regular", "Medium", "Bold")


def _download(url: str, timeout: float = 35.0, attempts: int = 4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "dicodePing-build/2.0.0"})
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if not payload:
                raise RuntimeError(f"Empty response from {url}")
            return payload
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(8, 2 ** (attempt - 1)))
    raise RuntimeError(f"Could not download {url} after {attempts} attempts: {last_error}")


def _verify_integrity(payload: bytes, integrity: str) -> None:
    algorithm, encoded = integrity.split("-", 1)
    if algorithm.lower() != "sha512":
        raise RuntimeError(f"Unsupported npm integrity algorithm: {algorithm}")
    actual = base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
    if actual != encoded:
        raise RuntimeError("Vazirmatn npm package integrity mismatch")


def _valid_font(payload: bytes) -> bool:
    return len(payload) >= 50_000 and payload[:4] in {
        b"\x00\x01\x00\x00",
        b"OTTO",
        b"true",
        b"ttcf",
    }


def prepare(*, android: bool = False) -> list[Path]:
    metadata = json.loads(_download(REGISTRY).decode("utf-8"))
    if str(metadata.get("version") or "") != VERSION:
        raise RuntimeError("Unexpected Vazirmatn package version returned by npm")
    dist = metadata.get("dist") or {}
    tarball_url = str(dist.get("tarball") or "")
    integrity = str(dist.get("integrity") or "")
    if not tarball_url or not integrity:
        raise RuntimeError("npm metadata does not contain tarball integrity")

    archive = _download(tarball_url, timeout=60.0)
    _verify_integrity(archive, integrity)

    desktop_dir = ROOT / "assets" / "fonts"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
        for weight in WEIGHTS:
            member_name = f"package/fonts/ttf/Vazirmatn-{weight}.ttf"
            member = package.getmember(member_name)
            source = package.extractfile(member)
            payload = source.read() if source else b""
            if not _valid_font(payload):
                raise RuntimeError(f"Invalid bundled font payload: {member_name}")
            destination = desktop_dir / f"Vazirmatn-{weight}.ttf"
            destination.write_bytes(payload)
            extracted.append(destination)

    manifest = {
        "package": PACKAGE,
        "version": VERSION,
        "integrity": integrity,
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in extracted},
    }
    (desktop_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if android:
        android_dir = ROOT / "dicodePing_android" / "app" / "src" / "main" / "res" / "font"
        android_dir.mkdir(parents=True, exist_ok=True)
        for path in extracted:
            weight = path.stem.rsplit("-", 1)[-1].lower()
            shutil.copy2(path, android_dir / f"vazirmatn_{weight}.ttf")
        family_xml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<font-family xmlns:android=\"http://schemas.android.com/apk/res/android\" xmlns:app=\"http://schemas.android.com/apk/res-auto\">
    <font android:font=\"@font/vazirmatn_regular\" android:fontStyle=\"normal\" android:fontWeight=\"400\" app:font=\"@font/vazirmatn_regular\" app:fontStyle=\"normal\" app:fontWeight=\"400\" />
    <font android:font=\"@font/vazirmatn_medium\" android:fontStyle=\"normal\" android:fontWeight=\"500\" app:font=\"@font/vazirmatn_medium\" app:fontStyle=\"normal\" app:fontWeight=\"500\" />
    <font android:font=\"@font/vazirmatn_bold\" android:fontStyle=\"normal\" android:fontWeight=\"700\" app:font=\"@font/vazirmatn_bold\" app:fontStyle=\"normal\" app:fontWeight=\"700\" />
</font-family>
"""
        (android_dir / "vazirmatn.xml").write_text(family_xml, encoding="utf-8")

    print("Prepared Vazirmatn 33.0.3: " + ", ".join(path.name for path in extracted))
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--android", action="store_true")
    args = parser.parse_args()
    prepare(android=args.android)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
