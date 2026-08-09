from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path, PurePosixPath

MANIFEST_SEPARATOR = "  "
PACKAGE_ONLY_PREFIXES = ("release-tools/",)
PACKAGE_ONLY_FILES = {
    "DEPLOY_RELEASE_206_STABLE.bat",
    "RELEASE_SOURCE_MANIFEST.sha256",
}
IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".gradle",
    ".idea",
    ".kotlin",
    ".cxx",
    ".externalNativeBuild",
    "build",
    "dist",
    "release",
    "release-assets",
    "artifacts",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(raw: str) -> Path:
    normalized = raw.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"Unsafe manifest path: {raw!r}")
    return Path(*pure.parts)


def read_manifest(path: Path) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if MANIFEST_SEPARATOR not in line:
            raise ValueError(f"Malformed manifest line {line_number}: {raw_line!r}")
        digest, raw_relative = line.split(MANIFEST_SEPARATOR, 1)
        digest = digest.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"Invalid SHA-256 on manifest line {line_number}")
        relative = safe_relative_path(raw_relative.strip())
        key = relative.as_posix().casefold()
        if key in seen:
            raise ValueError(f"Duplicate manifest path: {relative.as_posix()}")
        seen.add(key)
        entries.append((digest, relative))
    if not entries:
        raise ValueError("The release source manifest is empty")
    return entries


def should_ignore_package_file(relative: Path) -> bool:
    parts = relative.parts
    if any(part in IGNORED_DIRECTORY_NAMES for part in parts):
        return True
    posix = relative.as_posix()
    return posix in PACKAGE_ONLY_FILES or posix.startswith(PACKAGE_ONLY_PREFIXES)


def prune_destination(destination: Path, manifest_paths: set[str]) -> list[str]:
    """Remove base-branch files not present in the verified release snapshot.

    Existing manifest files are deliberately left in place before copy so Git
    retains their index modes. This avoids turning every historical 100755 file
    into 100644 when the publisher runs from a Windows-extracted ZIP.
    """
    removed: list[str] = []
    candidates = sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True)
    for candidate in candidates:
        try:
            relative = candidate.relative_to(destination)
        except ValueError:
            continue
        if not relative.parts or relative.parts[0] == ".git":
            continue
        posix = relative.as_posix()
        if candidate.is_symlink() or candidate.is_file():
            if posix.casefold() not in manifest_paths:
                candidate.unlink(missing_ok=True)
                removed.append(posix)
        elif candidate.is_dir():
            try:
                candidate.rmdir()
            except OSError:
                pass
    return sorted(removed, key=str.casefold)


def list_unmanifested_files(source: Path, manifest_paths: set[str]) -> list[str]:
    extras: list[str] = []
    for candidate in source.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(source)
        if should_ignore_package_file(relative):
            continue
        posix = relative.as_posix()
        if posix.casefold() not in manifest_paths:
            extras.append(posix)
    return sorted(extras, key=str.casefold)


def stage_snapshot(source: Path, destination: Path, manifest: Path) -> int:
    source = source.resolve()
    destination = destination.resolve()
    manifest = manifest.resolve()
    if source == destination:
        raise ValueError("Source and destination must be different directories")
    if not source.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source}")
    if not destination.is_dir():
        raise FileNotFoundError(f"Destination directory not found: {destination}")
    if not manifest.is_file():
        raise FileNotFoundError(f"Release manifest not found: {manifest}")

    entries = read_manifest(manifest)
    manifest_paths = {relative.as_posix().casefold() for _, relative in entries}
    removed = prune_destination(destination, manifest_paths)
    copied = 0
    for expected_digest, relative in entries:
        source_file = source / relative
        if not source_file.is_file():
            raise FileNotFoundError(f"Manifest file is missing: {relative.as_posix()}")
        actual_digest = sha256_file(source_file)
        if actual_digest != expected_digest:
            raise ValueError(
                f"Checksum mismatch for {relative.as_posix()}: "
                f"expected {expected_digest}, got {actual_digest}"
            )
        destination_file = destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        copied += 1

    extras = list_unmanifested_files(source, manifest_paths)
    print(f"Verified and staged {copied} manifest files.")
    if removed:
        print(f"Removed {len(removed)} tracked/base file(s) not present in the release snapshot.")
        for item in removed[:20]:
            print(f"  - {item}")
        if len(removed) > 20:
            print(f"  ... and {len(removed) - 20} more")
    if extras:
        print(f"Ignored {len(extras)} unlisted file(s) from the extracted folder.")
        for item in extras[:20]:
            print(f"  - {item}")
        if len(extras) > 20:
            print(f"  ... and {len(extras) - 20} more")
    return copied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify and stage only the files listed in the dicodePing release manifest."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        stage_snapshot(args.source, args.destination, args.manifest)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
