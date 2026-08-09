"""Fetch and verify the optional desktop cores for a release bundle."""
from __future__ import annotations

import argparse
import json
import shutil
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dicodeping.core_manager import CORE_CATALOG, download_core


def prepare(root: Path) -> dict[str, dict[str, str]]:
    destination = root / "core"
    destination.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict[str, str]] = {}
    for core_id in ("aether", "warp"):
        descriptor = CORE_CATALOG[core_id]
        source = download_core(core_id, stage=lambda value: print(f"[{core_id}] {value}", flush=True))
        target = destination / descriptor.executable_name
        shutil.copy2(source, target)
        target.chmod(0o755)
        result[core_id] = {
            "version": descriptor.version,
            "upstreamArchiveSha256": descriptor.sha256,
            "executable": descriptor.executable_name,
            "upstream": descriptor.upstream,
        }
    (destination / "bundled-cores.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    prepare(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
