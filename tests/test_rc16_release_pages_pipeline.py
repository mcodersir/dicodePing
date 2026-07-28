from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_pages_workflow_uses_current_artifact_and_required_permissions() -> None:
    workflow = read(".github/workflows/docs.yml")
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v4" in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "needs: build" in workflow
    assert "name: github-pages" in workflow
    assert "artifact_name: github-pages" in workflow
    assert "test -f docs/site/index.html" in workflow


def test_one_click_deployer_repairs_pages_and_purges_stale_tests() -> None:
    deploy = read("DEPLOY_PRERELEASE_RC16.bat")
    assert "tools\\purge_stale_release_tests.py" in deploy
    assert "tools\\configure_github_pages.ps1" in deploy
    assert "gh release delete" in deploy
    assert "gh auth login" in deploy
    assert "ONE-CLICK: CLONE + PRE-RELEASE + PAGES DEPLOY" in deploy

    pages = read("tools/configure_github_pages.ps1")
    assert "build_type=workflow" in pages
    assert "pages/deployments/$($deployment.sha)/cancel" in pages
    assert "gh run watch" in pages
    assert "workflow', 'run'" in pages


def test_stale_rc15_tests_are_removed_without_deleting_generic_tests(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    shutil.copytree(ROOT, workspace)

    stale = workspace / "tests" / "test_rc15_leftover.py"
    stale.write_text(
        'def test_old():\n'
        '    assert \'RELEASE_VERSION = "1.9.0-rc.15"\'\n'
        '    assert \'app_v190_rc15.py\'\n',
        encoding="utf-8",
    )
    generic = workspace / "tests" / "test_rc2_generic_leftover.py"
    generic.write_text("def test_generic():\n    assert 2 + 2 == 4\n", encoding="utf-8")

    script = workspace / "tools" / "purge_stale_release_tests.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not stale.exists()
    assert generic.exists()
