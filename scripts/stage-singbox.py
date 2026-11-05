#!/usr/bin/env python3
"""Stage verified stand-alone sing-box runtimes for desktop."""
import argparse
import hashlib
import io
import json
import pathlib
import tarfile
import urllib.request
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--rid', required=True, choices=['win-x64', 'linux-x64', 'osx-x64', 'osx-arm64'])
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
pins = json.loads(pathlib.Path(__file__).with_name('singbox-pins-4.9.94.json').read_text())
version = pins['version'].removeprefix('v')

def stage(suffix, directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    pin = pins['assets'][f'sing-box-{version}-{suffix}']
    with urllib.request.urlopen(pin['url'], timeout=90) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise ValueError(f'sing-box archive SHA-256 mismatch: {suffix}')
    if suffix.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = {pathlib.PurePosixPath(n).name: archive.read(n) for n in archive.namelist() if pathlib.PurePosixPath(n).name in ('sing-box.exe', 'LICENSE')}
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            files = {pathlib.PurePosixPath(n.name).name: archive.extractfile(n).read() for n in archive if n.isfile() and pathlib.PurePosixPath(n.name).name in ('sing-box', 'LICENSE')}
    binary = files['sing-box.exe' if suffix.endswith('.zip') else 'sing-box']
    path = directory / name
    path.write_bytes(binary)
    path.chmod(0o755)
    (directory / 'LICENSE-sing-box.txt').write_bytes(files['LICENSE'])
    print('Verified', path, flush=True)

suffix = {'win-x64': 'windows-amd64.zip', 'linux-x64': 'linux-amd64.tar.gz',
          'osx-x64': 'darwin-amd64.tar.gz', 'osx-arm64': 'darwin-arm64.tar.gz'}[args.rid]
stage(suffix, args.output, 'sing-box.exe' if args.rid == 'win-x64' else 'sing-box')
