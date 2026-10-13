#!/usr/bin/env python3
"""Stage checksum-pinned Aether and its transport helpers; never substitute an unverified binary."""
import argparse, hashlib, json, pathlib, shutil, tarfile, tempfile, urllib.request, zipfile
args = argparse.ArgumentParser()
args.add_argument("--android", action="store_true")
args.add_argument("--rid")
args.add_argument("--output", required=True)
ns = args.parse_args()
pins = json.loads(pathlib.Path(__file__).with_name("runtime-pins-4.4.0.json").read_text())
platforms = {"arm64-v8a": "android-arm64.tar.gz", "armeabi-v7a": "android-armv7.tar.gz", "x86_64": "android-x86_64.tar.gz"} if ns.android else {"win-x64": "windows-x86_64.zip", "linux-x64": "linux-x86_64.tar.gz", "osx-x64": "macos-x86_64.tar.gz", "osx-arm64": "macos-arm64.tar.gz"}
for platform, suffix in platforms.items():
    if not ns.android and platform != ns.rid: continue
    asset = "aether-" + suffix
    with tempfile.TemporaryDirectory() as folder:
        folder = pathlib.Path(folder)
        archive = folder / asset
        urllib.request.urlretrieve("https://github.com/CluvexStudio/Aether/releases/download/" + pins["aether"] + "/" + asset, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != pins["assets"][asset]: raise RuntimeError("Aether checksum mismatch: " + asset)
        extracted = folder / "unpacked"
        if suffix.endswith(".zip"):
            with zipfile.ZipFile(archive) as bundle: bundle.extractall(extracted)
        else:
            with tarfile.open(archive) as bundle: bundle.extractall(extracted, filter="data")
        if ns.android:
            target = pathlib.Path(ns.output) / platform
            target.mkdir(parents=True, exist_ok=True)
            for source, dest in [("aether", "libaether.so"), ("psiphon-tunnel-core", "libpsiphon-tunnel-core.so"), ("lyrebird", "liblyrebird.so")]:
                found = next(extracted.rglob(source), None)
                if found is None: raise RuntimeError("Missing helper " + source + " in " + asset)
                shutil.copy2(found, target / dest)
                (target / dest).chmod(0o755)
        else:
            target = pathlib.Path(ns.output)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(extracted, target, dirs_exist_ok=True)
            for candidate in target.rglob("*"):
                if candidate.is_file() and candidate.suffix not in [".txt", ".md"]: candidate.chmod(0o755)
        print("Verified and staged", asset)
