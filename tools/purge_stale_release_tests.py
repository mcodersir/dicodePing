from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_RE = re.compile(r'^RELEASE_VERSION\s*=\s*["\'](?P<version>\d+\.\d+\.\d+-rc\.\d+)["\']', re.MULTILINE)
RC_RE = re.compile(r'-rc\.(?P<rc>\d+)')
RELEASE_TEST_NAME_RE = re.compile(r'^test_rc(?P<rc>\d+)_', re.IGNORECASE)
STALE_MARKERS = (
    re.compile(r'1\.9\.0-rc\.(?P<rc>\d+)'),
    re.compile(r'app_v190_rc(?P<rc>\d+)\.py'),
    re.compile(r'DEPLOY_PRERELEASE_RC(?P<rc>\d+)\.bat'),
    re.compile(r'versionCode\s*=\s*(?P<code>\d+)'),
)


def current_release() -> tuple[str, int]:
    constants = (ROOT / 'dicodeping' / 'constants.py').read_text(encoding='utf-8')
    match = RELEASE_RE.search(constants)
    if not match:
        raise RuntimeError('RELEASE_VERSION was not found in dicodeping/constants.py')
    version = match.group('version')
    rc_match = RC_RE.search(version)
    if not rc_match:
        raise RuntimeError(f'Unsupported release version: {version}')
    return version, int(rc_match.group('rc'))


def is_stale_release_test(path: Path, current_rc: int) -> bool:
    name = path.name.lower()
    if name.startswith('test_v'):
        return True
    if name.startswith(f'test_rc{current_rc}_'):
        return False

    # RC10+ test modules are release snapshots. They may contain generic
    # regression assertions and therefore cannot be detected reliably by
    # scanning their text for a version string. A ZIP extracted over an older
    # workspace can leave these files behind, so remove every older RC10+
    # module by filename. Keep the long-lived generic suites test_rc2.py ...
    # test_rc9.py and similarly named generic fixtures.
    filename_match = RELEASE_TEST_NAME_RE.match(name)
    if filename_match:
        filename_rc = int(filename_match.group('rc'))
        if filename_rc >= 10 and filename_rc != current_rc:
            return True

    text = path.read_text(encoding='utf-8', errors='ignore')
    referenced_rcs: set[int] = set()
    for pattern in STALE_MARKERS[:3]:
        for match in pattern.finditer(text):
            referenced_rcs.add(int(match.group('rc')))

    # Delete only tests tied to a previous release. Generic regression tests such
    # as test_rc2.py are retained when they do not hard-code obsolete metadata.
    return bool(referenced_rcs) and current_rc not in referenced_rcs


def purge(*, dry_run: bool = False) -> list[Path]:
    _, current_rc = current_release()
    tests_dir = ROOT / 'tests'
    removed: list[Path] = []
    if not tests_dir.is_dir():
        return removed

    for path in sorted(tests_dir.glob('test_*.py')):
        if not is_stale_release_test(path, current_rc):
            continue
        removed.append(path)
        if not dry_run:
            path.unlink(missing_ok=True)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description='Remove stale version-locked tests from an overlaid RC workspace.')
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
