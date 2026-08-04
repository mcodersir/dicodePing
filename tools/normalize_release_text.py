from __future__ import annotations

import argparse
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".css",
    ".gradle",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".kt",
    ".kts",
    ".md",
    ".properties",
    ".ps1",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "gradlew",
}
CRLF_SUFFIXES = {".bat", ".cmd", ".ps1"}
SKIP_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".kotlin",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "release",
    "release-assets",
    "venv",
    "vendor",
}


def is_text_path(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def iter_text_files(root: Path):
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if is_text_path(path):
            yield path


def normalized_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip(" \t") for line in lines]
    while lines and not lines[-1]:
        lines.pop()
    normalized = "\n".join(lines)
    if normalized:
        normalized += "\n"
    newline = "\r\n" if path.suffix.lower() in CRLF_SUFFIXES else "\n"
    if newline != "\n":
        normalized = normalized.replace("\n", newline)
    return normalized.encode("utf-8")


def normalize_tree(root: Path, *, check: bool) -> int:
    changed: list[str] = []
    for path in iter_text_files(root):
        expected = normalized_bytes(path)
        actual = path.read_bytes()
        if actual == expected:
            continue
        changed.append(path.relative_to(root).as_posix())
        if not check:
            path.write_bytes(expected)

    if changed:
        action = "Require normalization" if check else "Normalized"
        print(f"{action}: {len(changed)} text file(s)")
        for item in changed[:30]:
            print(f"  - {item}")
        if len(changed) > 30:
            print(f"  ... and {len(changed) - 30} more")
    else:
        print("Release text files are normalized.")
    return 1 if check and changed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize release source line endings and trailing whitespace."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(f"[ERROR] Release root not found: {root}", file=sys.stderr)
        return 2
    return normalize_tree(root, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
