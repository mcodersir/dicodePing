#!/usr/bin/env python3
"""Stage the official native sing-box CLI for each Android ABI, with digest checks."""
import hashlib, io, json, pathlib, tarfile, urllib.request
pins = json.loads(pathlib.Path(__file__).with_name('singbox-android-pins.json').read_text())
abis = {'arm':'armeabi-v7a', 'arm64':'arm64-v8a', '386':'x86', 'amd64':'x86_64'}
for asset in pins['assets']:
    architecture = asset['name'].removesuffix('.tar.gz').rsplit('-',1)[1]
    data = urllib.request.urlopen(asset['url'], timeout=120).read()
    if hashlib.sha256(data).hexdigest() != asset['sha256']: raise RuntimeError('Digest mismatch: '+asset['name'])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        entry = next(m for m in archive.getmembers() if pathlib.PurePosixPath(m.name).name == 'sing-box' and m.isfile())
        target = pathlib.Path('apps/android/app/libs')/abis[architecture]/'libsingbox.so'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.extractfile(entry).read()); target.chmod(0o755)
        print('Verified native sing-box', abis[architecture])
