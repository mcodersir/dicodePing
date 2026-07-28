from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rc16_deployer_bootstraps_missing_android_signing_secrets() -> None:
    deployer = (ROOT / "DEPLOY_PRERELEASE_RC16.bat").read_text("utf-8")
    helper = (ROOT / "tools/bootstrap_android_signing.ps1").read_text("utf-8")

    assert "call :ensure_android_signing" in deployer
    assert "tools\\bootstrap_android_signing.ps1" in deployer
    assert ":check_secrets" not in deployer
    assert "gh secret set --repo $Repository --app actions --env-file" in helper
    assert "GetFolderPath('MyDocuments')" in helper
    assert "dicodePing-signing" in helper
    assert "release.jks" in helper
    assert "-storepass:env" in helper
    assert "-keypass:env" in helper
    assert "ANDROID_KEYSTORE_BASE64" in helper
