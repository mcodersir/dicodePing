#!/usr/bin/env python3
"""Bundle the independent sing-box engine. The Fox engine is deliberately unchanged."""
import argparse, hashlib, json, os, pathlib, platform, shutil, subprocess, tarfile, tempfile, urllib.request, zipfile
from verify_elf_alignment import verify_elf

ROOT = pathlib.Path(__file__).resolve().parents[1]
pins = json.loads((ROOT / 'scripts/runtime-pins-4.9.991.json').read_text())['singbox']
parser = argparse.ArgumentParser()
parser.add_argument('--rid', choices=['win-x64', 'linux-x64', 'osx-x64', 'osx-arm64'])
parser.add_argument('--android', action='store_true')
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
if not args.android and not args.rid: parser.error('--rid or --android is required')
platforms = ['arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86'] if args.android else [args.rid]
if args.android:
    # Upstream prebuilt executables still use 4 KB LOAD alignment. Build the
    # exact pinned source with NDK linking so 16 KB Android can load every ABI.
    source = ROOT / 'native-upstream-singbox'
    if not source.exists(): subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'fetch', '--depth', '1', 'https://github.com/SagerNet/sing-box.git', pins['source_commit']], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != pins['source_commit']:
        raise RuntimeError('sing-box source commit mismatch')
    ndk = pathlib.Path(os.environ.get('NDK_HOME') or pathlib.Path(os.environ['ANDROID_HOME']) / 'ndk/29.0.14206865')
    host = 'darwin-x86_64' if platform.system() == 'Darwin' else 'linux-x86_64'
    for rid, arch, triple in [('arm64-v8a','arm64','aarch64-linux-android'), ('armeabi-v7a','arm','armv7a-linux-androideabi'), ('x86_64','amd64','x86_64-linux-android'), ('x86','386','i686-linux-android')]:
        target = (args.output / rid / 'libsingbox.so').resolve(); target.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy(); env.update(GOOS='android', GOARCH=arch, CGO_ENABLED='1', GOARM='7', CC=str(ndk / 'toolchains/llvm/prebuilt' / host / 'bin' / (triple+'29-clang')))
        subprocess.run(['go','build','-mod=readonly','-trimpath','-buildmode=pie','-tags=with_gvisor,with_quic,with_wireguard,with_utls,with_clash_api', '-ldflags=-s -w -buildid= -extldflags=-Wl,-z,max-page-size=16384 -X github.com/sagernet/sing-box/constant.Version='+pins['version'],'-o',str(target),'./cmd/sing-box'],cwd=source,env=env,check=True)
        verify_elf(target.read_bytes(), rid, str(target))
        target.chmod(0o755)
        print('Built 16 KB sing-box:', rid)
    legal=ROOT/'apps/android/app/src/main/assets/singbox';legal.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'licenses/LICENSE-sing-box',legal/'LICENSE.txt')
    (legal/'runtime-versions.json').write_text(json.dumps({'version':pins['version'],'source_commit':pins['source_commit']},indent=2)+'\n')
    raise SystemExit(0)
for rid in platforms:
    asset = pins['assets'][rid]
    with tempfile.TemporaryDirectory() as directory:
        work = pathlib.Path(directory)
        archive = work / asset['name']
        urllib.request.urlretrieve(asset['url'], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != asset['sha256']:
            raise RuntimeError('sing-box checksum mismatch: ' + asset['name'])
        extracted = work / 'unpacked'
        if archive.suffix == '.zip':
            with zipfile.ZipFile(archive) as bundle: bundle.extractall(extracted)
        else:
            with tarfile.open(archive) as bundle: bundle.extractall(extracted, filter='data')
        name = 'sing-box.exe' if rid == 'win-x64' else 'sing-box'
        source = next(extracted.rglob(name), None)
        if source is None: raise RuntimeError('sing-box executable missing')
        target = args.output / rid / 'libsingbox.so' if args.android else args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target); target.chmod(0o755)
        if args.android:
            verify_elf(target.read_bytes(), rid, str(target))
        else:
            result = subprocess.run([str(target.resolve()), 'version'], capture_output=True, text=True, check=True, timeout=20)
            if pins['version'] not in result.stdout: raise RuntimeError('sing-box version mismatch')
        metadata = {'version': pins['version'], 'asset_sha256': asset['sha256'], 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
        (target.parent / ('singbox-runtime.json' if args.android else 'runtime-versions.json')).write_text(json.dumps(metadata, indent=2)+'\n')
        # Keep license attribution with every native binary distribution.
        shutil.copy2(ROOT / 'licenses/LICENSE-sing-box', target.parent / 'LICENSE-sing-box.txt')
        print('Verified and staged', asset['name'])
