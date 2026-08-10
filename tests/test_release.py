from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import queue
import subprocess
import sys

import dicodeping.service as service_module
from dicodeping.client.host import CoreHostClient
from dicodeping.constants import DEFAULT_SUBSCRIPTION_URL, RELEASE_VERSION, VERSION
from dicodeping.models import ServerRecord, SourceDefinition
from dicodeping.protocols import extract_configs, parse_endpoint
from dicodeping.scanner import _id as scanner_record_id
from dicodeping.service import AppService
from dicodeping.subscription import SubscriptionPayload, _decode_github_contents
from dicodeping.sources import normalize_sources


class Store:
    def __init__(self) -> None:
        self.rows: list[ServerRecord] = []
        self.settings: dict = {}

    def load_servers(self):
        return [replace(row) for row in self.rows]

    def save_servers(self, rows):
        self.rows = [replace(row) for row in rows]

    def load_settings(self):
        return dict(self.settings)

    def save_settings(self, settings):
        self.settings = dict(settings)


class Runtime:
    def __init__(self) -> None:
        self.synced: list[tuple[str, str]] = []

    def sync_source(self, source_id: str, content: str):
        self.synced.append((source_id, content))
        return [{
            "id": f"profile-{source_id}",
            "name": "Primary Profile",
            "type": "VLESS",
            "host": "example.com",
            "port": 443,
            "network": "ws",
            "security": "tls",
            "share_uri": "vless://test@example.com:443?security=tls&type=ws",
        }]

    def latency(self, ids):
        return {str(value): 42 for value in ids}

    def connect(self, profile_id, *, tun=False, system_proxy="on"):
        return {"connected": True, "profile_id": profile_id, "tun": tun, "system_proxy": system_proxy}

    def disconnect(self):
        return {"connected": False}


def test_version_and_primary_source_are_v3():
    assert VERSION == "3.0.0"
    assert RELEASE_VERSION == "3.0.0-pre.1"
    assert DEFAULT_SUBSCRIPTION_URL.endswith("mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt")


def test_normalize_sources_forces_authoritative_primary_source():
    rows = normalize_sources({"sources": [{
        "id": "default", "name": "Primary", "url": "https://example.invalid/replaced", "enabled": False,
    }]})
    assert rows[0].id == "default"
    assert rows[0].url == DEFAULT_SUBSCRIPTION_URL
    assert rows[0].enabled is True
    assert rows[0].is_default is True


def test_github_contents_decoder():
    payload = '{"encoding":"base64","content":"dmxlc3M6Ly9leGFtcGxl"}'
    assert _decode_github_contents(payload) == "vless://example"


def test_refresh_hands_raw_subscription_to_runtime_and_keeps_scanner(monkeypatch):
    store = Store()
    store.rows = [ServerRecord(
        id="scanner-old", name="Scanner", protocol="VLESS", host="scan.example", port=443,
        config_blob="vless://scan", source_id="scanner-sub", source_name="Scanner", core_profile_id="scan-profile",
    )]
    runtime = Runtime()
    service = AppService(store, runtime)
    source = SourceDefinition("default", "Primary", DEFAULT_SUBSCRIPTION_URL, is_default=True)
    monkeypatch.setattr(service_module, "fetch_subscription", lambda _: SubscriptionPayload(source, "RAW-SUBSCRIPTION"))

    rows = service.refresh()
    assert runtime.synced == [("default", "RAW-SUBSCRIPTION")]
    assert any(row.core_profile_id == "profile-default" for row in rows)
    assert any(row.source_id == "scanner-sub" for row in rows)


def test_latency_uses_runtime_profile_ids():
    store = Store()
    store.rows = [ServerRecord(
        id="a", name="A", protocol="VLESS", host="a.example", port=443,
        config_blob="vless://a", core_profile_id="runtime-a",
    )]
    runtime = Runtime()
    service = AppService(store, runtime)
    rows = service.test_latency()
    assert rows[0].ping_ms == 42
    assert rows[0].status == "online"


def test_refresh_keeps_product_identity_when_runtime_profile_id_changes(monkeypatch):
    store = Store()
    runtime = Runtime()
    service = AppService(store, runtime)
    source = SourceDefinition("default", "Primary", DEFAULT_SUBSCRIPTION_URL, is_default=True)
    monkeypatch.setattr(service_module, "fetch_subscription", lambda _: SubscriptionPayload(source, "RAW"))

    first = service.refresh()[0]
    first.favorite = True
    store.save_servers([first])

    original = runtime.sync_source
    def changed(source_id: str, content: str):
        rows = original(source_id, content)
        rows[0]["id"] = "new-runtime-profile-id"
        return rows
    runtime.sync_source = changed

    second = service.refresh()[0]
    assert second.id == first.id
    assert second.core_profile_id == "new-runtime-profile-id"
    assert second.favorite is True


def test_corehost_process_exit_wakes_pending_requests_immediately():
    client = CoreHostClient()
    inbox: queue.Queue[dict] = queue.Queue(maxsize=1)
    client._responses["request"] = inbox
    client._fail_pending("runtime crashed")
    response = inbox.get_nowait()
    assert response == {"ok": False, "error": "runtime crashed"}


def test_scanner_record_identity_can_follow_share_uri_not_runtime_id():
    uri = "vless://stable@example.com:443?security=tls"
    first = scanner_record_id(uri)
    second = scanner_record_id(uri)
    assert first == second
    assert first != scanner_record_id(uri + "&type=ws")

def test_scanner_extracts_hysteria2_and_hy2_profiles():
    text = "one hysteria2://secret@example.com:443?sni=edge.example#A\ntwo hy2://token@[2001:db8::1]:8443?insecure=1#B"
    rows = extract_configs(text)
    assert len(rows) == 2
    assert rows[0].startswith("hysteria2://")
    assert rows[1].startswith("hy2://")


def test_hysteria2_endpoint_alias_is_normalized():
    endpoint = parse_endpoint("hy2://token@example.com:8443?sni=edge.example")
    assert endpoint is not None
    assert endpoint.protocol == "hysteria2"
    assert endpoint.host == "example.com"
    assert endpoint.port == 8443



def test_sing_box_runtime_digests_are_pinned_without_missing_checksum_asset():
    from tools.fetch_runtime_assets import SING_BOX_ASSETS

    expected = {
        "sing-box-1.13.12-windows-amd64.zip": "e93fc531134eb1beb4efa3c74990a24e48456098a31c03b60d5ddf17f223cf98",
        "sing-box-1.13.12-linux-amd64.tar.gz": "1540533adb3df24f5ad5f14b5c7ca3dbc2401b10a1c1eb278fcadcada47ec6c4",
        "sing-box-1.13.12-darwin-arm64.tar.gz": "43eef86f0ea4a79c3696974f397a963c46a457ee46d1ffac9aa913944a5fc986",
        "sing-box-1.13.12-darwin-amd64.tar.gz": "f3275316451bf1983bc059599c69c8ed0232d53a619d15cfd535f95cc9a4477a",
    }
    assert SING_BOX_ASSETS == expected

    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "runtime_assets/RUNTIME_ASSETS.lock.json").read_text(encoding="utf-8"))
    assert lock["desktop"]["sing_box"]["assets"] == expected
    fetch_source = (root / "tools/fetch_runtime_assets.py").read_text(encoding="utf-8")
    engine_source = (root / "tools/prepare_engine.py").read_text(encoding="utf-8")
    assert "checksum_name =" not in fetch_source
    assert "checksum_text =" not in engine_source
    assert 'download(f"{base}/{checksum_name}"' not in fetch_source


def test_prepare_runtime_is_verification_only_and_offline_packager_exists():
    root = Path(__file__).resolve().parents[1]
    prepare = (root / "PREPARE_V3_RUNTIME.bat").read_text(encoding="utf-8")
    repair = (root / "REPAIR_V3_RUNTIME.bat").read_text(encoding="utf-8")
    package = (root / "MAKE_COMPLETE_V3_ZIP.bat").read_text(encoding="utf-8")
    source = (root / "tools/package_complete_v3.py").read_text(encoding="utf-8")
    assert "--verify-only" in prepare
    assert "py -3 tools\\fetch_runtime_assets.py --verify-only" in prepare
    assert "py -3 tools\\fetch_runtime_assets.py\n" not in prepare
    assert "-m tools.package_complete_v3 --verify-output" in prepare
    assert "goto" not in prepare.lower()
    assert "fetch_runtime_assets.py" in repair
    assert "PREPARE_V3_RUNTIME.bat" in package
    assert "verify_runtime_bundle" in source
    assert "PROJECT_ROOT = Path(__file__).resolve().parents[1]" in source
    assert "dicodePing-{RELEASE}-complete.zip" in source


def test_complete_packager_imports_in_direct_and_module_modes():
    root = Path(__file__).resolve().parents[1]
    direct = subprocess.run(
        [sys.executable, "tools/package_complete_v3.py", "--help"],
        cwd=root, text=True, capture_output=True, timeout=30, check=False,
    )
    assert direct.returncode == 0, direct.stderr
    assert "Build the self-contained" in direct.stdout

    module = subprocess.run(
        [sys.executable, "-m", "tools.package_complete_v3", "--help"],
        cwd=root, text=True, capture_output=True, timeout=30, check=False,
    )
    assert module.returncode == 0, module.stderr
    assert "Build the self-contained" in module.stdout


def test_publisher_uses_existing_git_auth_and_ci_token():
    root = Path(__file__).resolve().parents[1]
    publisher = (root / "PUBLISH_3.0.0_PRE1.bat").read_text(encoding="utf-8")
    mirror = (root / "RELEASE_V3_PRERELEASE.bat").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/release-v3.yml").read_text(encoding="utf-8")

    assert publisher == mirror
    assert "set \"REPO=mcodersir/dicodePing\"" in publisher
    assert "git clone" in publisher
    assert "sync_release_tree.py" in publisher
    assert 'for %%I in ("%~dp0.") do set "SOURCE=%%~fI"' in publisher
    assert 'set "SOURCE=%~dp0"' not in publisher
    assert 'if exist "%SOURCE%\\.git" (' in publisher
    assert '"%SOURCE%\\tools\\sync_release_tree.py" --source "%SOURCE%" --destination "%WORK%"' in publisher
    assert "robocopy" not in publisher.lower()
    assert "git push origin" in publisher
    assert "git tag -a" in publisher
    assert "REMOTE_TAG_EXISTS" in publisher
    assert "git push --force origin" in publisher
    assert "--allow-empty" in publisher
    assert "never overwrites an existing release tag" not in publisher.lower()
    assert "GH_TOKEN is not set" not in publisher
    assert "if not defined GH_TOKEN" not in publisher
    assert "gh auth setup-git" not in publisher
    assert "gh.exe is missing or not logged in. That is OK" in publisher
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "--prerelease" in workflow
    assert "gh release edit" in workflow
    assert "gh release upload" in workflow
    assert "--clobber" in workflow


def test_release_tree_sync_preserves_git_and_uses_only_manifest(tmp_path):
    import hashlib

    from tools.sync_release_tree import sync

    source = tmp_path / "source"
    destination = tmp_path / "checkout"
    source.mkdir()
    destination.mkdir()
    (destination / ".git").mkdir()
    (destination / ".git" / "sentinel").write_text("keep", encoding="utf-8")
    (destination / "stale.txt").write_text("remove", encoding="utf-8")

    tracked = {
        "app.py": b"print('v3')\n",
        "nested/config.json": b"{\"version\":3}\n",
    }
    manifest_rows = []
    for relative, data in tracked.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest_rows.append(f"{hashlib.sha256(data).hexdigest()}  {relative}")
    (source / "local-runtime.bin").write_bytes(b"must-not-be-published")
    (source / "SOURCE_MANIFEST.sha256").write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")

    count = sync(source, destination)

    assert count == 2
    assert (destination / ".git" / "sentinel").read_text(encoding="utf-8") == "keep"
    assert not (destination / "stale.txt").exists()
    assert not (destination / "local-runtime.bin").exists()
    assert (destination / "app.py").read_bytes() == tracked["app.py"]
    assert (destination / "nested/config.json").read_bytes() == tracked["nested/config.json"]
    assert (destination / "SOURCE_MANIFEST.sha256").is_file()



def test_desktop_build_entrypoints_import_in_direct_and_module_modes():
    root = Path(__file__).resolve().parents[1]
    for module in ("build_windows", "build_linux", "build_macos"):
        direct = subprocess.run(
            [sys.executable, f"tools/{module}.py", "--help"],
            cwd=root, text=True, capture_output=True, timeout=30, check=False,
        )
        assert direct.returncode == 0, f"{module} direct: {direct.stderr}"
        assert "ModuleNotFoundError" not in direct.stderr

        packaged = subprocess.run(
            [sys.executable, "-m", f"tools.{module}", "--help"],
            cwd=root, text=True, capture_output=True, timeout=30, check=False,
        )
        assert packaged.returncode == 0, f"{module} module: {packaged.stderr}"
        assert "ModuleNotFoundError" not in packaged.stderr


def test_release_workflow_uses_module_builders_and_node24_actions():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/release-v3.yml").read_text(encoding="utf-8")
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    codeql = (root / ".github/workflows/codeql.yml").read_text(encoding="utf-8")

    for command in (
        "python -m tools.build_windows --skip-install",
        "python -m tools.build_linux --skip-install",
        "python -m tools.build_macos --skip-install",
    ):
        assert command in workflow

    combined = "\n".join((workflow, ci, codeql))
    assert "actions/checkout@v4" not in combined
    assert "actions/setup-python@v5" not in combined
    assert "actions/setup-dotnet@v4" not in combined
    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/setup-dotnet@v6" in workflow
    assert "actions/setup-java@v5" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "actions/download-artifact@v8" in workflow
    assert "actions/upload-artifact@v4" not in workflow
    assert "actions/download-artifact@v4" not in workflow
