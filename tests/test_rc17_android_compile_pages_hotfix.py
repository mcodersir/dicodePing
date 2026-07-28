from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_scanner_runtime_tuning_uses_the_declared_repository_field() -> None:
    source = read(
        "dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt"
    )
    assert "private val repo = AppRepository.get(context)" in source
    assert "RuntimeTuning.detect(context, repo.settings.resourceMode)" in source
    assert "repository.settings.resourceMode" not in source


def test_android_source_reference_validator_runs_everywhere() -> None:
    validator = read("tools/validate_android_source_references.py")
    workflow = read(".github/workflows/release.yml")
    deploy = read("DEPLOY_PRERELEASE_RC17.bat")
    build_sh = read("dicodePing_android/build_apk.sh")
    build_bat = read("dicodePing_android/build_apk.bat")

    assert "repository.settings.resourceMode" in validator
    assert "validate_android_source_references.py" in workflow
    assert "validate_android_source_references.py" in deploy
    assert "validate_android_source_references.py" in build_sh
    assert "validate_android_source_references.py" in build_bat


def test_pages_helper_retries_transient_github_cli_failures() -> None:
    pages = read("tools/configure_github_pages.ps1")
    deploy = read("DEPLOY_PRERELEASE_RC17.bat")

    assert "Test-TransientGhFailure" in pages
    assert "TLS handshake timeout" in pages
    assert "[PAGES][RETRY]" in pages
    assert "$ErrorActionPreference = 'Continue'" in pages
    assert "call :ensure_gh" in deploy
    assert "call :run_pages_attempt 1" in deploy
    assert "Full deployment attempt %~1/3" in deploy
    assert "timeout /t 15 /nobreak" in deploy
    assert deploy.index("call :ensure_gh") < deploy.index("[1/10] Cloning")
