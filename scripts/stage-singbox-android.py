#!/usr/bin/env python3
"""Build the pinned Android sing-box CLI as an NDK-linked, 16 KB compatible PIE."""
import os, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_elf_alignment import verify_elf
source = ROOT / 'native-singbox'
if not source.exists():
    subprocess.run(['git','clone','--depth','1','--branch','v1.14.3','https://github.com/SagerNet/sing-box.git',str(source)],check=True)
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip() == '7054cac5124465ffdb145870d7c01885566711b1'
ndk = pathlib.Path(os.environ.get('NDK_HOME') or os.environ.get('ANDROID_NDK_HOME') or pathlib.Path(os.environ['ANDROID_HOME'])/'ndk/29.0.14206865')
# Keep the upstream CLI features. No FFI/JNI API or custom protocol replacement.
tags = (source/'release/DEFAULT_BUILD_TAGS_OTHERS').read_text().strip()
for abi, arch, triple in [('arm64-v8a','arm64','aarch64-linux-android'),('armeabi-v7a','arm','armv7a-linux-androideabi'),('x86_64','amd64','x86_64-linux-android'),('x86','386','i686-linux-android')]:
    env = os.environ.copy()
    env.update(GOOS='android', GOARCH=arch, CGO_ENABLED='1', GOTOOLCHAIN='local', CC=str(ndk/'toolchains/llvm/prebuilt/linux-x86_64/bin'/f'{triple}29-clang'))
    if arch == 'arm': env['GOARM'] = '7'
    target = ROOT/'apps/android/app/libs'/abi/'libsingbox.so'; target.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['go','build','-trimpath','-buildmode=pie','-tags',tags,'-ldflags=-s -w -buildid= -checklinkname=0 -X github.com/sagernet/sing-box/constant.Version=1.14.3 -linkmode=external -extldflags=-Wl,-z,max-page-size=16384','-o',str(target),'./cmd/sing-box'],cwd=source,env=env,check=True)
    target.chmod(0o755)
    verify_elf(target.read_bytes(), abi, str(target))
    print('Built Android sing-box 1.14.3, 16 KB PIE:',abi,flush=True)
