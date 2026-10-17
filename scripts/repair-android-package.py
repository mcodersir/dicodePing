#!/usr/bin/env python3
"""Repackage release 4.9.2 without changing any executable or resource payload."""
import concurrent.futures, hashlib, json, os, pathlib, re, shutil, struct, subprocess, urllib.request, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN = json.loads((ROOT / "scripts/android-package-revision-2.json").read_text())
OUT = ROOT / "dist-install"
INPUT = ROOT / "install-input"
TOOLS = pathlib.Path(os.environ["ANDROID_HOME"]) / "build-tools/37.0.0"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))$", re.I)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def revise_manifest(data, expected, replacement):
    data = bytearray(data)
    strings = []
    pos = 8
    changed = 0
    while pos < len(data):
        kind, header, size = struct.unpack_from("<HHI", data, pos)
        assert size >= header >= 8 and pos + size <= len(data), "Invalid binary XML chunk"
        if kind == 1:
            count, _, flags, start, _ = struct.unpack_from("<5I", data, pos + 8)
            def length(offset):
                if flags & 256:
                    n = data[offset]
                    return (((n & 127) << 8) | data[offset + 1], offset + 2) if n & 128 else (n, offset + 1)
                n = struct.unpack_from("<H", data, offset)[0]
                return (((n & 32767) << 16) | struct.unpack_from("<H", data, offset + 2)[0], offset + 4) if n & 32768 else (n, offset + 2)
            for i in range(count):
                offset = pos + start + struct.unpack_from("<I", data, pos + header + 4 * i)[0]
                n, offset = length(offset)
                if flags & 256:
                    n, offset = length(offset)
                strings.append(data[offset:offset + n * (1 if flags & 256 else 2)].decode("utf-8" if flags & 256 else "utf-16le"))
        if kind == 0x102:
            _, name, start, width, count = struct.unpack_from("<IIHHH", data, pos + 16)
            if strings[name] == "manifest":
                for i in range(count):
                    offset = pos + 16 + start + width * i
                    _, name, raw, _, _, value_type, value = struct.unpack_from("<IIIHBBI", data, offset)
                    if strings[name] == "versionCode":
                        assert raw == 0xffffffff and value_type in (0x10, 0x11) and value == expected
                        struct.pack_into("<I", data, offset + 16, replacement)
                        changed += 1
        pos += size
    assert changed == 1, "Expected one integer versionCode"
    return bytes(data)

def fetch(abi):
    name = f"DicodePing-4.9.2-{abi}.apk"
    target = INPUT / name
    if not target.exists():
        with urllib.request.urlopen(f"https://github.com/mcodersir/dicodePing/releases/download/v4.9.2/{name}", timeout=90) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)
    assert digest(target.read_bytes()) == PIN["sha256"][abi], f"Original APK changed: {abi}"
    return abi, target

def verify_payload(original, rebuilt, manifest):
    with zipfile.ZipFile(original) as before, zipfile.ZipFile(rebuilt) as after:
        original_names = {i.filename for i in before.infolist() if not SIGNATURE.fullmatch(i.filename)}
        new_names = {i.filename for i in after.infolist() if not SIGNATURE.fullmatch(i.filename)}
        assert original_names == new_names, "APK payload file list changed"
        hashes = {}
        for name in sorted(original_names):
            actual = after.read(name)
            if name == "AndroidManifest.xml":
                assert actual == manifest, "Unexpected manifest edits"
            else:
                assert actual == before.read(name), f"Executable/resource payload changed: {name}"
            hashes[name] = digest(actual)
        assert after.getinfo("resources.arsc").compress_type == zipfile.ZIP_STORED
        return digest(json.dumps(hashes, sort_keys=True).encode())

def main():
    OUT.mkdir(exist_ok=True)
    INPUT.mkdir(exist_ok=True)
    inputs = dict(concurrent.futures.ThreadPoolExecutor(max_workers=5).map(fetch, PIN["sha256"]))
    records = []
    for abi, original in inputs.items():
        name = original.name
        unsigned = INPUT / (name + ".unsigned")
        aligned = INPUT / (name + ".aligned")
        old_code = PIN["old_base"] + PIN["suffixes"][abi]
        new_code = PIN["new_base"]
        with zipfile.ZipFile(original) as before, zipfile.ZipFile(unsigned, "w", allowZip64=False) as after:
            manifest = revise_manifest(before.read("AndroidManifest.xml"), old_code, new_code)
            for entry in before.infolist():
                if not SIGNATURE.fullmatch(entry.filename):
                    after.writestr(entry, manifest if entry.filename == "AndroidManifest.xml" else before.read(entry.filename))
        subprocess.run([str(TOOLS / "zipalign"), "-f", "-P", "16", "4", str(unsigned), str(aligned)], check=True)
        rebuilt = OUT / name
        subprocess.run([str(TOOLS / "apksigner"), "sign", "--ks", os.environ["DICODE_KEYSTORE_PATH"],
            "--ks-pass", "env:DICODE_KEYSTORE_PASSWORD", "--ks-key-alias", os.environ["DICODE_KEY_ALIAS"],
            "--key-pass", "env:DICODE_KEY_PASSWORD", "--v1-signing-enabled", "true", "--v2-signing-enabled", "true",
            "--v3-signing-enabled", "true", "--v4-signing-enabled", "false", "--out", str(rebuilt), str(aligned)], check=True)
        result = subprocess.run([str(TOOLS / "apksigner"), "verify", "--min-sdk-version", "21", "--verbose", "--print-certs", str(rebuilt)], check=True, capture_output=True, text=True).stdout
        certs = re.findall(r"certificate SHA-256 digest: ([0-9a-fA-F]+)", result)
        assert certs and all(c.lower() == PIN["certificate_sha256"] for c in certs), "Upgrade certificate changed"
        for scheme in (1, 2, 3):
            assert re.search(rf"Verified using v{scheme} scheme .*: true", result), result
        subprocess.run([str(TOOLS / "zipalign"), "-c", "-P", "16", "4", str(rebuilt)], check=True)
        badging = subprocess.run([str(TOOLS / "aapt2"), "dump", "badging", str(rebuilt)], check=True, capture_output=True, text=True).stdout
        assert "name='ir.dicode.ping.fdroid'" in badging and "versionName='4.9.2'" in badging
        assert f"versionCode='{new_code}'" in badging, badging
        minimum = re.search(r"(?m)^(?:minSdkVersion|sdkVersion):'(\d+)(?:\.0)?'", badging)
        target = re.search(r"(?m)^targetSdkVersion:'(\d+)(?:\.0)?'", badging)
        assert minimum and target and (int(minimum[1]), int(target[1])) == (29, 36), badging
        payload = verify_payload(original, rebuilt, manifest)
        records.append({"name": name, "abi": abi, "original_sha256": PIN["sha256"][abi], "sha256": digest(rebuilt.read_bytes()),
            "version_code": new_code, "size": rebuilt.stat().st_size, "payload_manifest_sha256": payload})
        unsigned.unlink()
        aligned.unlink()
        print(f"PASS {abi}: same application payload and signing key; versionCode={new_code}; V1/V2/V3 verified", flush=True)
    (OUT / "SHA256SUMS-android.txt").write_text("".join(f"{r['sha256']}  {r['name']}\n" for r in sorted(records, key=lambda r: r["name"])))
    (OUT / "android-build2-provenance.json").write_text(json.dumps({"revision": 2, "source_commit": PIN["source_commit"],
        "packaging_commit": os.environ.get("GITHUB_SHA"), "certificate_sha256": PIN["certificate_sha256"], "packages": records}, indent=2) + "\n")

if __name__ == "__main__":
    main()
