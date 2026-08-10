from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
from pathlib import Path

MANIFEST_NAME = "SOURCE_MANIFEST.sha256"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(root: Path, relative: str) -> Path:
    rel = Path(relative.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise RuntimeError(f"unsafe manifest path: {relative!r}")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"manifest path escapes source tree: {relative!r}") from exc
    return candidate


def _load_manifest(source: Path) -> list[tuple[str, str, Path]]:
    manifest = source / MANIFEST_NAME
    if not manifest.is_file():
        raise RuntimeError(f"missing {MANIFEST_NAME}: {manifest}")

    rows: list[tuple[str, str, Path]] = []
    seen: set[str] = set()
    for number, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip("\ufeff\r\n")
        if not line:
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RuntimeError(f"invalid manifest line {number}: {raw!r}") from exc
        expected = expected.strip().lower()
        relative = relative.strip().replace("\\", "/")
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise RuntimeError(f"invalid SHA-256 on manifest line {number}")
        if relative == MANIFEST_NAME:
            raise RuntimeError(f"{MANIFEST_NAME} must not list itself")
        if relative in seen:
            raise RuntimeError(f"duplicate manifest path: {relative}")
        seen.add(relative)
        path = _safe_member(source, relative)
        if not path.is_file():
            raise RuntimeError(f"manifest file is missing: {relative}")
        actual = _sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"source checksum mismatch: {relative}\n"
                f"expected {expected}\n"
                f"actual   {actual}"
            )
        rows.append((expected, relative, path))
    if not rows:
        raise RuntimeError(f"{MANIFEST_NAME} is empty")
    return rows


def _make_writable(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _remove_error(func, path, _exc_info) -> None:
    _make_writable(path)
    func(path)


def _remove_entry(path: Path) -> None:
    is_junction = getattr(path, "is_junction", lambda: False)()
    if path.is_symlink() or is_junction:
        try:
            path.unlink()
        except IsADirectoryError:
            path.rmdir()
        return
    if path.is_dir():
        shutil.rmtree(path, onerror=_remove_error)
        return
    _make_writable(str(path))
    path.unlink(missing_ok=True)


def sync(source: Path, destination: Path) -> int:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise RuntimeError("source and destination must be different directories")
    if not (destination / ".git").exists():
        raise RuntimeError(f"destination is not a Git checkout: {destination}")

    # Verify the complete source package *before* touching the cloned checkout.
    rows = _load_manifest(source)

    # Preserve only Git metadata. Everything else comes from the signed source manifest,
    # so local runtime downloads/build output can never leak into the release commit.
    for child in destination.iterdir():
        if child.name == ".git":
            continue
        _remove_entry(child)

    for expected, relative, src in rows:
        dst = destination / Path(relative)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        actual = _sha256(dst)
        if actual != expected:
            raise RuntimeError(f"destination checksum mismatch after copy: {relative}")

    shutil.copy2(source / MANIFEST_NAME, destination / MANIFEST_NAME)
    print(f"[ok] Synced {len(rows)} manifest-tracked Version 3 files into the clean Git checkout.")
    print("[ok] Preserved .git and ignored local runtime/build/dist/cache files that are not in the source manifest.")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely sync the Version 3 source package into a cloned Git checkout.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        sync(args.source, args.destination)
        return 0
    except Exception as exc:
        print(f"Release source sync failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
