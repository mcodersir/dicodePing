from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_deployer_uses_self_contained_workflow_validator() -> None:
    deployer = text("DEPLOY_RELEASE_200.bat")
    assert "tools\\validate_workflow_yaml.py" in deployer
    assert 'import yaml,pathlib' not in deployer
    assert "tools\\vendor\\pyyaml\\yaml\\__init__.py" in deployer
    assert "tools\\vendor\\pyyaml\\LICENSE" in deployer


def test_vendored_pyyaml_is_pinned_and_licensed() -> None:
    init = text("tools/vendor/pyyaml/yaml/__init__.py")
    assert "__version__ = '6.0.3'" in init or '__version__ = "6.0.3"' in init
    assert (ROOT / "tools/vendor/pyyaml/LICENSE").is_file()
    assert "MIT" in text("tools/vendor/pyyaml/README.md")


def test_workflow_validator_runs_without_site_packages() -> None:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-S", "tools/validate_workflow_yaml.py"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "vendored PyYAML 6.0.3" in completed.stdout


def test_validator_rejects_duplicate_keys(tmp_path: Path) -> None:
    workflow = tmp_path / "duplicate.yml"
    workflow.write_text(
        "name: first\nname: second\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: []\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-S", "tools/validate_workflow_yaml.py", str(workflow)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 1
    assert "duplicate key" in completed.stdout
