#!/usr/bin/env python3
"""Build the auditable Fox helper from this release's source (no prebuilt downloads)."""
import argparse, hashlib, json, os, pathlib, platform, shutil, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--rid', choices=['win-x64', 'linux-x64', 'osx-x64', 'osx-arm64'])
parser.add_argument('--android', action='store_true')
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
go = os.environ.get('DICODE_GO', 'go')
assert subprocess.check_output([go, 'version'], text=True).split()[2] == 'go1.27.3', 'Use the pinned Go 1.27.3 toolchain'
versions = {}
license_modules = {}
def build(goos, arch, output, android=False):
    env = os.environ.copy(); env.update(GOOS=goos, GOARCH=arch, CGO_ENABLED='0', GOTOOLCHAIN='local')
    if arch == 'arm': env['GOARM'] = '7'
    extra = []
    if android:
        extra = ['-buildmode=pie']; env['CGO_ENABLED'] = '1'
        ndk = pathlib.Path(os.environ.get('NDK_HOME') or pathlib.Path(os.environ['ANDROID_HOME']) / 'ndk/29.0.14206865')
        triple = {'arm64':'aarch64-linux-android', 'arm':'armv7a-linux-androideabi', 'amd64':'x86_64-linux-android', '386':'i686-linux-android'}[arch]
        host = 'darwin-x86_64' if platform.system() == 'Darwin' else 'linux-x86_64'
        cc = ndk / 'toolchains/llvm/prebuilt' / host / 'bin' / (triple + '29-clang')
        assert cc.is_file(), 'Pinned Android NDK 29 is required'; env['CC'] = str(cc)
    output = output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([go, 'build', '-tags=with_utls,with_quic,badlinkname', '-trimpath', '-ldflags=-s -w -buildid= -checklinkname=0', *extra, '-o', str(output), '.'], cwd=ROOT/'apps/fox-helper', env=env, check=True)
    # Collect only modules actually linked for this OS/architecture, preserving
    # the notices of dependencies newly embedded with the sing-box transport.
    packages = subprocess.check_output([go, 'list', '-deps', '-json', '-tags=with_utls,with_quic,badlinkname', '.'], cwd=ROOT/'apps/fox-helper', env=env, text=True)
    decoder = json.JSONDecoder()
    while packages.strip():
        package, end = decoder.raw_decode(packages.lstrip())
        packages = packages.lstrip()[end:]
        module = package.get('Module')
        if module and not module.get('Main'):
            module = module.get('Replace') or module
            if module.get('Dir'):
                license_modules[(module['Path'], module.get('Version', ''))] = pathlib.Path(module['Dir'])
    output.chmod(0o755)
    versions[str(output.relative_to(args.output.resolve()))] = {'version':'4.9.93', 'go':'1.27.3', 'engine':'Vauth/sing-box v1.0.0-masque', 'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
if args.android:
    for abi, arch in [('arm64-v8a','arm64'),('armeabi-v7a','arm'),('x86_64','amd64'),('x86','386')]: build('android', arch, args.output/abi/'libdicodefox.so', True)
    legal = ROOT/'apps/android/app/src/main/assets/fox'; legal.mkdir(parents=True, exist_ok=True)
else:
    assert args.rid
    goos, arch = {'win-x64':('windows','amd64'), 'linux-x64':('linux','amd64'), 'osx-x64':('darwin','amd64'), 'osx-arm64':('darwin','arm64')}[args.rid]
    build(goos, arch, args.output/('dicode-fox.exe' if goos == 'windows' else 'dicode-fox')); legal = args.output
for name in ['LICENSE-FoxyVPN.txt', 'LICENSE-sing-box.txt', 'NOTICE.md']: shutil.copy2(ROOT/'apps/fox-helper'/name, legal/name)
notices = []
for (module, revision), directory in sorted(license_modules.items()):
    notices.append(f'\n{module} {revision}\n' + '=' * 72 + '\n')
    for file in sorted(directory.iterdir()):
        if file.is_file() and file.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE', 'AUTHORS')):
            notices.append(f'\n{file.name}\n{file.read_text(errors="replace")}\n')
(legal/'THIRD_PARTY_NOTICES-Go.txt').write_text(''.join(notices), encoding='utf-8')
goroot = pathlib.Path(subprocess.check_output([go, 'env', 'GOROOT'], text=True).strip())
shutil.copy2(goroot/'LICENSE', legal/'LICENSE-Go.txt')
shutil.copy2(ROOT/'LICENSE', legal/'LICENSE-DicodePing.txt')
(legal/'runtime-versions.json').write_text(json.dumps(versions, indent=2)+'\n')
print('Built Fox 4.9.93:', ', '.join(versions))
