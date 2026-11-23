"""Stage the browser downloads and require an exact checksum manifest for each."""
import hashlib
import pathlib
import re
import shutil
import sys

root, page, version = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
expected = {f"DicodePing-{version}-{name}" for name in re.findall(r'data-asset="([^"]+)"', page.read_text())}
manifests = sorted(root.glob("SHA256SUMS-*.txt"))
assert len(expected) == 21 and len(manifests) == 9
checksums = {}
for manifest in manifests:
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        checksum, name = line.split(maxsplit=1)
        name = name.strip().lstrip("*")
        assert name not in checksums
        checksums[name] = checksum
assert checksums.keys() == expected
output = pathlib.Path("release-assets")
output.mkdir()
for name in sorted(expected):
    path = root / name
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == checksums[name], name
    shutil.copyfile(path, output / name)
for manifest in manifests:
    shutil.copyfile(manifest, output / manifest.name)
