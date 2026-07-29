from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_RE = re.compile(
    r'^RELEASE_VERSION\s*=\s*["\'](?P<version>\d+\.\d+\.\d+(?:-rc\.\d+)?)["\']',
    re.MULTILINE,
)
RELEASE_TEST_NAME_RE = re.compile(r'^test_rc(?P<rc>\d+)_', re.IGNORECASE)


def current_release() -> tuple[str, str]:
    constants = (ROOT / 'dicodeping' / 'constants.py').read_text(encoding='utf-8')
    match = RELEASE_RE.search(constants)
    if not match:
        raise RuntimeError('RELEASE_VERSION was not found in dicodeping/constants.py')
    version = match.group('version')
    base = version.split('-rc.', 1)[0]
    digits = base.replace('.', '')
    if '-rc.' in version:
        rc = version.rsplit('-rc.', 1)[1]
        prefix = f'test_v{digits}_rc{rc}'
    else:
        prefix = f'test_v{digits}_stable'
    return version, prefix.lower()


def is_stale_release_test(path: Path, current_version_prefix: str) -> bool:
    name = path.name.lower()
    if name.startswith('test_v'):
        return not name.startswith(current_version_prefix)

    filename_match = RELEASE_TEST_NAME_RE.match(name)
    if filename_match and int(filename_match.group('rc')) >= 10:
        return True

    text = path.read_text(encoding='utf-8', errors='ignore')
    obsolete_markers = (
        r'1\.9\.0-rc\.\d+',
        r'app_v190_rc\d+\.py',
        r'DEPLOY_PRERELEASE_RC(?:1[0-9]|[2-9])\.bat',
    )
    return any(re.search(pattern, text) for pattern in obsolete_markers)


def purge(*, dry_run: bool = False) -> list[Path]:
    _, current_version_prefix = current_release()
    tests_dir = ROOT / 'tests'
    removed: list[Path] = []
    if not tests_dir.is_dir():
        return removed
    for path in sorted(tests_dir.glob('test_*.py')):
        if not is_stale_release_test(path, current_version_prefix):
            continue
        removed.append(path)
        if not dry_run:
            path.unlink(missing_ok=True)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description='Remove stale version-locked tests from an overlaid release workspace.')
    parser.add_argument('--check', action='store_true', help='Report stale files without deleting them.')
    args = parser.parse_args()
    version, _ = current_release()
    removed = purge(dry_run=args.check)
    action = 'would remove' if args.check else 'removed'
    if removed:
        print(f'Stale release-test cleanup for {version}:')
        for path in removed:
            print(f'  - {action}: {path.relative_to(ROOT).as_posix()}')
    else:
        print(f'No stale version-locked tests found for {version}.')
    return 2 if args.check and removed else 0


if __name__ == '__main__':
    raise SystemExit(main())
