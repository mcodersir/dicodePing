#!/usr/bin/env python3
"""Reject a download-site deployment until every linked package is published."""
import json
import pathlib
import re
import sys


def verify(release, tag, html):
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Expected a stable version tag")
    if release.get("tag_name") != tag or release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("Release is not publicly stable")
    links = re.findall(r'data-asset="([^"]+)"', html)
    if len(links) != 16 or len(set(links)) != 16:
        raise ValueError("Download page must list all 16 distinct packages")
    version = tag[1:]
    base = f"https://github.com/mcodersir/dicodePing/releases/download/{tag}/"
    assets = {asset["name"]: asset for asset in release.get("assets", [])}
    for suffix in links:
        name = f"DicodePing-{version}-{suffix}"
        asset = assets.get(name, {})
        if asset.get("size", 0) <= 0 or asset.get("browser_download_url") != base + name:
            raise ValueError(f"Missing published package: {name}")
        if base + name not in html:
            raise ValueError(f"Stale download link: {name}")


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parents[1]
    verify(json.loads(pathlib.Path(sys.argv[1]).read_text()), sys.argv[2], (root / "web/index.html").read_text())
    print("PASS all download links point to published stable packages")
