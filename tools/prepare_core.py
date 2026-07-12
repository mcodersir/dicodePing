from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dicodeping.xray import ensure_wintun, ensure_xray


def prepare_core() -> Path:
    target = ROOT / "core"
    target.mkdir(parents=True, exist_ok=True)

    executable = ensure_xray(print)
    ensure_wintun(executable, progress=print)
    for name in (executable.name, "geoip.dat", "geosite.dat", "wintun.dll"):
        source = executable.parent / name
        if source.exists():
            destination = target / name
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)

    required = [target / ("xray.exe" if sys.platform.startswith("win") else "xray")]
    if sys.platform.startswith("win"):
        required.append(target / "wintun.dll")
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Missing core files: " + ", ".join(missing))

    print(f"Core prepared at: {target}")
    return target


def main() -> int:
    try:
        prepare_core()
    except Exception as exc:
        print(f"Core preparation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
