#!/usr/bin/env python3
"""Stage checksum-pinned Aether and its transport helpers; never substitute an unverified binary."""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, tarfile, tempfile, urllib.request, zipfile
from verify_elf_alignment import verify_elf
args = argparse.ArgumentParser()
args.add_argument("--android", action="store_true")
args.add_argument("--rid")
args.add_argument("--output", required=True)
ns = args.parse_args()
pins = json.loads(pathlib.Path(__file__).with_name("runtime-pins-4.9.7.json").read_text())
platforms = {"arm64-v8a": "android-arm64.tar.gz", "armeabi-v7a": "android-armv7.tar.gz", "x86_64": "android-x86_64.tar.gz"} if ns.android else {"win-x64": "windows-x86_64.zip", "linux-x64": "linux-x86_64.tar.gz", "osx-x64": "macos-x86_64.tar.gz", "osx-arm64": "macos-arm64.tar.gz"}
def build_x64_transports(target, work):
    # The upstream ARM64 helpers already use 64 KB LOAD alignment. Its static
    # x86_64 Go helpers use 4 KB; rebuild the same sources with 16 KB rounding.
    source_pins = pins["android_transport_sources"]
    env = os.environ.copy()
    env.pop("GOROOT", None)
    env.pop("GOFLAGS", None)
    env.update(GOOS="linux", GOARCH="amd64", CGO_ENABLED="0")
    lyre = source_pins["lyrebird"]
    env["GOTOOLCHAIN"] = lyre["go"]
    module = json.loads(subprocess.check_output(
        ["go", "mod", "download", "-json", lyre["module"] + "@" + lyre["version"]], env=env, text=True))
    if hashlib.sha256(pathlib.Path(module["Zip"]).read_bytes()).hexdigest() != lyre["zip_sha256"]:
        raise RuntimeError("Lyrebird source checksum mismatch")
    subprocess.run(["go", "build", "-mod=readonly", "-trimpath", "-ldflags=-s -w -R 16384",
        "-o", str((target/"liblyrebird.so").resolve()), "./cmd/lyrebird"], cwd=module["Dir"], env=env, check=True)
    psiphon = source_pins["psiphon"]
    source = work/"psiphon-source"
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "fetch", "--depth", "1", psiphon["repository"], psiphon["commit"]], check=True)
    subprocess.run(["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"], check=True)
    if subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() != psiphon["commit"]:
        raise RuntimeError("Psiphon source commit mismatch")
    # psiphon-tls mirrors crypto/tls structs. Go 1.27 changes their layout;
    # the current security-patched Go 1.26 line preserves its required ABI.
    env["GOTOOLCHAIN"] = psiphon["go"]
    subprocess.run(["go", "build", "-mod=vendor", "-trimpath", "-ldflags=-s -w -R 16384",
        "-o", str((target/"libpsiphon-tunnel-core.so").resolve()), "./ConsoleClient"], cwd=source, env=env, check=True)
    for name in ("liblyrebird.so", "libpsiphon-tunnel-core.so"):
        binary = target/name
        binary.chmod(0o755)
        verify_elf(binary.read_bytes(), "x86_64", str(binary))
        smoke = subprocess.run([str(binary.resolve()), "-version"], check=True, capture_output=True, text=True, timeout=15)
        if not smoke.stdout.strip(): raise RuntimeError("Transport version check returned no output: " + name)
        print("Built and executed 16 KB Android transport:", name, flush=True)

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
            if platform == "x86_64": build_x64_transports(target, folder)
            for binary in target.glob("*.so"):
                verify_elf(binary.read_bytes(), platform, str(binary))
        else:
            target = pathlib.Path(ns.output)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(extracted, target, dirs_exist_ok=True)
            for candidate in target.rglob("*"):
                if candidate.is_file() and candidate.suffix not in [".txt", ".md"]: candidate.chmod(0o755)
        print("Verified and staged", asset)
