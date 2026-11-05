#!/usr/bin/env python3
"""Stage checksum-pinned Aether and its transport helpers; never substitute an unverified binary."""
import platform as host_platform
import argparse, hashlib, json, os, pathlib, shutil, subprocess, tarfile, tempfile, urllib.request, zipfile
from verify_elf_alignment import verify_elf
args = argparse.ArgumentParser()
args.add_argument("--android", action="store_true")
args.add_argument("--rid")
args.add_argument("--output", required=True)
ns = args.parse_args()
pins = json.loads(pathlib.Path(__file__).with_name("runtime-pins-4.9.93.json").read_text())
platforms = {"arm64-v8a": "android-arm64.tar.gz", "armeabi-v7a": "android-armv7.tar.gz", "x86_64": "android-x86_64.tar.gz"} if ns.android else {"win-x64": "windows-x86_64.zip", "linux-x64": "linux-x86_64.tar.gz", "osx-x64": "macos-x86_64.tar.gz", "osx-arm64": "macos-arm64.tar.gz"}
def build_transports(target, work, goos, arch, android=False):
    # Rebuild every architecture from the verified current transport sources.
    # Android static helpers must retain 16 KB LOAD alignment.
    source_pins = pins["android_transport_sources"]
    env = os.environ.copy()
    env.pop("GOROOT", None)
    env.pop("GOFLAGS", None)
    env.update(GOOS=goos, GOARCH=arch, CGO_ENABLED="0")
    if arch == "arm": env["GOARM"] = "7"
    ldflags = "-s -w -R 16384" if android else "-s -w"
    lyre_name = "liblyrebird.so" if android else ("lyrebird.exe" if goos == "windows" else "lyrebird")
    psiphon_name = "libpsiphon-tunnel-core.so" if android else ("psiphon-tunnel-core.exe" if goos == "windows" else "psiphon-tunnel-core")
    lyre = source_pins["lyrebird"]
    env["GOTOOLCHAIN"] = lyre["go"]
    module = json.loads(subprocess.check_output(
        ["go", "mod", "download", "-json", lyre["module"] + "@" + lyre["version"]], env=env, text=True))
    if hashlib.sha256(pathlib.Path(module["Zip"]).read_bytes()).hexdigest() != lyre["zip_sha256"]:
        raise RuntimeError("Lyrebird source checksum mismatch")
    subprocess.run(["go", "build", "-mod=readonly", "-trimpath", "-ldflags="+ldflags,
        "-o", str((target/lyre_name).resolve()), "./cmd/lyrebird"], cwd=module["Dir"], env=env, check=True)
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
    subprocess.run(["go", "build", "-mod=vendor", "-trimpath", "-ldflags="+ldflags,
        "-o", str((target/psiphon_name).resolve()), "./ConsoleClient"], cwd=source, env=env, check=True)
    for name in (lyre_name, psiphon_name):
        binary = target/name
        binary.chmod(0o755)
        if android: verify_elf(binary.read_bytes(), {"arm64":"arm64-v8a","arm":"armeabi-v7a","amd64":"x86_64"}[arch], str(binary))
        host_os = {"Linux":"linux","Darwin":"darwin","Windows":"windows"}.get(host_platform.system())
        host_arch = {"x86_64":"amd64","AMD64":"amd64","arm64":"arm64","aarch64":"arm64"}.get(host_platform.machine())
        if (goos, arch) == (host_os, host_arch):
            smoke = subprocess.run([str(binary.resolve()), "-version"], check=True, capture_output=True, text=True, timeout=15)
            if not (smoke.stdout+smoke.stderr).strip(): raise RuntimeError("Transport version check returned no output: " + name)
        print("Built pinned transport:", goos, arch, name, flush=True)

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
            build_transports(target, folder, "linux", {"arm64-v8a":"arm64","armeabi-v7a":"arm","x86_64":"amd64"}[platform], True)
            for binary in target.glob("*.so"):
                verify_elf(binary.read_bytes(), platform, str(binary))
        else:
            target = pathlib.Path(ns.output)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(extracted, target, dirs_exist_ok=True)
            goos, arch = {"win-x64":("windows","amd64"),"linux-x64":("linux","amd64"),"osx-x64":("darwin","amd64"),"osx-arm64":("darwin","arm64")}[ns.rid]
            executable = next(target.rglob("aether.exe" if goos == "windows" else "aether"))
            transport_dir = executable.parent / "pt"
            transport_dir.mkdir(parents=True, exist_ok=True)
            build_transports(transport_dir, folder, goos, arch)
            for candidate in target.rglob("*"):
                if candidate.is_file() and candidate.suffix not in [".txt", ".md"]: candidate.chmod(0o755)
        print("Verified and staged", asset)
