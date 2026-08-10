from __future__ import annotations

import argparse
import shutil
from pathlib import Path

FONT_SUFFIXES = {".ttf", ".otf", ".woff", ".woff2"}


def clean(root: Path, *, clean_outputs: bool = True) -> list[Path]:
    """Remove generated build products while leaving release inputs intact."""
    removed: list[Path] = []

    assets = root / "assets"
    if assets.is_dir():
        for path in assets.rglob("*"):
            if path.is_file() and path.suffix.lower() in FONT_SUFFIXES:
                path.unlink(missing_ok=True)
                removed.append(path)

    if clean_outputs:
        for relative in ("build", "dist", "release", ".pytest_cache"):
            path = root / relative
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(path)

    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean generated Version 3 build products.")
    parser.add_argument("--keep-outputs", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    removed = clean(root, clean_outputs=not args.keep_outputs)
    if removed:
        print("Removed generated files:")
        for path in removed:
            print(f"  - {path.relative_to(root)}")
    else:
        print("Workspace is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
