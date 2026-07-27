from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_deploy_does_not_abort_when_release_already_exists() -> None:
    deploy = (ROOT / "DEPLOY_PRERELEASE_RC4.bat").read_text("utf-8")
    assert "It will NOT block deployment and will be updated in place" in deploy
    assert "This recovery build will not replace a published release" not in deploy
    assert "TRIGGER_REL=.github\\release-triggers\\v1.9.0-rc.4.txt" in deploy
    assert "git push --force origin" in deploy
    assert '-CommitSha "%HEAD_SHA%"' in deploy


def test_workflow_is_triggered_once_from_recovery_marker_and_overwrites_assets() -> None:
    workflow = (ROOT / ".github/workflows/v1.9.0-rc.4-release.yml").read_text("utf-8")
    assert 'branches:\n      - main' in workflow
    assert 'paths:\n      - ".github/release-triggers/v1.9.0-rc.4.txt"' in workflow
    assert 'tags:\n      - "v1.9.0-rc.4"' not in workflow
    assert "overwrite_files: true" in workflow
    assert "target_commitish: ${{ github.sha }}" in workflow


def test_release_waiter_tracks_exact_commit_and_required_assets() -> None:
    waiter = (ROOT / "tools/wait_for_github_release.ps1").read_text("utf-8")
    assert "[string]$CommitSha" in waiter
    assert "Where-Object { $_.head_sha -eq $CommitSha }" in waiter
    assert "Existing release pages are ignored until this exact run succeeds" in waiter
    for asset in (
        "dicodePing-v1.9.0-rc.4-windows-x64.exe",
        "dicodePing-v1.9.0-rc.4-linux-x86_64.tar.gz",
        "dicodePing-v1.9.0-rc.4-macos-arm64.dmg",
        "dicodePing-v1.9.0-rc.4-macos-x86_64.dmg",
        "dicodePing-v1.9.0-rc.4-android.apk",
    ):
        assert asset in waiter
