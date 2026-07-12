from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dicodeping.constants import VERSION, WINTUN_SHA256, WINTUN_VERSION, XRAY_VERSION

REPOSITORY = "https://github.com/mcodersir/dicodePing"
ANDROID_CORE_VERSION = "26.6.2"
ANDROID_CORE_SHA256 = "367d6b2f74e62c974c61210c56802127812be4c9410a83a6b8b6cac765a7595e"


def spdx_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9.-]+", "-", value).strip("-")
    return clean or "unknown"


def git_revision() -> str:
    from_env = os.environ.get("GITHUB_SHA", "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", from_env):
        return from_env.lower()
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "uncommitted"


def package(
    *,
    name: str,
    version: str,
    download: str = "NOASSERTION",
    license_id: str = "NOASSERTION",
    checksum: str | None = None,
    supplier: str = "NOASSERTION",
) -> dict[str, object]:
    item: dict[str, object] = {
        "SPDXID": f"SPDXRef-Package-{spdx_id(name)}-{spdx_id(version)}",
        "name": name,
        "versionInfo": version,
        "downloadLocation": download,
        "filesAnalyzed": False,
        "licenseConcluded": license_id,
        "licenseDeclared": license_id,
        "copyrightText": "NOASSERTION",
        "supplier": supplier,
    }
    if checksum:
        item["checksums"] = [{"algorithm": "SHA256", "checksumValue": checksum.lower()}]
    return item


packages: list[dict[str, object]] = [
    package(
        name="dicodePing",
        version=VERSION,
        download=REPOSITORY,
        license_id="MIT",
        supplier="Organization: dicodePing contributors",
    ),
    package(
        name="Xray-core",
        version=XRAY_VERSION,
        download=f"https://github.com/XTLS/Xray-core/releases/tag/v{XRAY_VERSION}",
        license_id="MPL-2.0",
        supplier="Organization: XTLS",
    ),
    package(
        name="Wintun",
        version=WINTUN_VERSION,
        download=f"https://www.wintun.net/builds/wintun-{WINTUN_VERSION}.zip",
        license_id="GPL-2.0-only",
        checksum=WINTUN_SHA256,
        supplier="Organization: WireGuard LLC",
    ),
    package(
        name="AndroidLibXrayLite",
        version=ANDROID_CORE_VERSION,
        download=(
            "https://github.com/2dust/AndroidLibXrayLite/releases/download/"
            f"v{ANDROID_CORE_VERSION}/libv2ray.aar"
        ),
        license_id="LGPL-3.0-only",
        checksum=ANDROID_CORE_SHA256,
        supplier="Organization: AndroidLibXrayLite contributors",
    ),
]

seen = {(str(item["name"]).lower(), str(item["versionInfo"])) for item in packages}

for req in ROOT.rglob("requirements*.txt"):
    if any(part in {".git", "build", "dist", ".venv", "venv"} for part in req.parts):
        continue
    for raw in req.read_text("utf-8", errors="ignore").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "http:", "https:", "git+")):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", line)
        if not match:
            continue
        name = match.group(1)
        requirement_spec = match.group(2).strip()
        exact = re.fullmatch(r"==\s*([A-Za-z0-9_.+-]+)", requirement_spec)
        version = exact.group(1) if exact else (requirement_spec or "NOASSERTION")
        license_by_name = {
            "pyside6": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
            "pyinstaller": "GPL-2.0-or-later WITH Bootloader-exception",
        }
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        packages.append(
            package(
                name=name,
                version=version,
                download=f"https://pypi.org/project/{name}/{version}/" if version != "NOASSERTION" else f"https://pypi.org/project/{name}/",
                license_id=license_by_name.get(name.lower(), "NOASSERTION"),
            )
        )

for gradle in [*ROOT.rglob("build.gradle"), *ROOT.rglob("build.gradle.kts")]:
    if any(part in {".git", "build", ".gradle"} for part in gradle.parts):
        continue
    text = gradle.read_text("utf-8", errors="ignore")
    for group, artifact, version in re.findall(r'["\']([\w.-]+):([\w.-]+):([^"\']+)["\']', text):
        name = f"{group}:{artifact}"
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        apache_groups = (
            "androidx.",
            "com.android.",
            "com.google.android.",
            "com.squareup.okhttp3",
            "org.jetbrains.kotlin",
        )
        packages.append(
            package(
                name=name,
                version=version,
                download=f"https://central.sonatype.com/artifact/{group}/{artifact}/{version}",
                license_id="Apache-2.0" if group.startswith(apache_groups) else "NOASSERTION",
            )
        )

root_id = packages[0]["SPDXID"]
relationships = [
    {
        "spdxElementId": root_id,
        "relationshipType": "DEPENDS_ON",
        "relatedSpdxElement": item["SPDXID"],
    }
    for item in packages[1:]
]

revision = git_revision()
namespace_seed = f"{VERSION}:{revision}".encode("utf-8")
namespace_suffix = hashlib.sha256(namespace_seed).hexdigest()[:20]
created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

document = {
    "spdxVersion": "SPDX-2.3",
    "dataLicense": "CC0-1.0",
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": f"dicodePing-{VERSION}-source-and-build-sbom",
    "documentNamespace": f"{REPOSITORY}/sbom/{VERSION}/{namespace_suffix}",
    "creationInfo": {
        "creators": ["Tool: tools/generate_sbom.py"],
        "created": created,
        "licenseListVersion": "3.25",
    },
    "documentDescribes": [root_id],
    "packages": packages,
    "relationships": relationships,
    "comment": f"Generated for source revision {revision}.",
}

output = ROOT / "artifacts" / "SBOM.spdx.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", "utf-8")
print(output)
