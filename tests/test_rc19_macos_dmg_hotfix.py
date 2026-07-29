from __future__ import annotations

import subprocess
from pathlib import Path

from tools import build_macos

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_hdiutil_resource_busy_is_retryable() -> None:
    result = subprocess.CompletedProcess(
        ["hdiutil", "create"],
        1,
        stdout="",
        stderr="hdiutil: create failed - Resource busy",
    )
    assert build_macos._retryable_hdiutil_failure(result)


def test_permission_or_format_errors_are_not_silently_retried() -> None:
    result = subprocess.CompletedProcess(
        ["hdiutil", "create"],
        1,
        stdout="",
        stderr="hdiutil: create failed - permission denied",
    )
    assert not build_macos._retryable_hdiutil_failure(result)


def test_macos_builder_uses_fresh_staging_atomic_output_and_verification() -> None:
    builder = read("tools/build_macos.py")
    assert "DMG_CREATE_ATTEMPTS = 6" in builder
    assert "TemporaryDirectory" in builder
    assert '"hdiutil", "verify"' in builder
    assert "shutil.move(str(temporary_output), str(output))" in builder
    assert '"resource busy"' in builder
    assert "transient DiskImages failure" in builder


def test_release_workflow_retries_complete_macos_build_and_verifies_dmg() -> None:
    workflow = read(".github/workflows/release.yml")
    assert "for attempt in 1 2 3; do" in workflow
    assert "macOS build failed after three complete attempts" in workflow
    assert 'hdiutil verify "release/dicodePing-v1.9.0-rc.19-macos-${{ matrix.architecture }}.dmg"' in workflow
    assert 'test -s "release/dicodePing-v1.9.0-rc.19-macos-${{ matrix.architecture }}.dmg"' in workflow


def test_dmg_creator_recovers_from_resource_busy_and_publishes_verified_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "dicodePing.app").mkdir()
    output = tmp_path / "release" / "dicodePing.dmg"
    calls = {"create": 0, "verify": 0}

    def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["hdiutil", "create"]:
            calls["create"] += 1
            candidate = Path(command[-1])
            if calls["create"] == 1:
                return subprocess.CompletedProcess(command, 1, "", "Resource busy")
            candidate.write_bytes(b"verified-dmg")
            return subprocess.CompletedProcess(command, 0, "created", "")
        if command[:2] == ["hdiutil", "verify"]:
            calls["verify"] += 1
            return subprocess.CompletedProcess(command, 0, "verified", "")
        raise AssertionError(command)

    monkeypatch.setattr(build_macos, "_run_captured", fake_run)
    monkeypatch.setattr(build_macos, "_sync_filesystem", lambda: None)
    monkeypatch.setattr(build_macos.time, "sleep", lambda _seconds: None)

    build_macos._create_dmg_with_retry(
        source_root=source,
        output=output,
        volume_name="dicodePing test",
        root=tmp_path,
    )

    assert calls == {"create": 2, "verify": 1}
    assert output.read_bytes() == b"verified-dmg"
