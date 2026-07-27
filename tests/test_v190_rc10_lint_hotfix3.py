from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_splash_literal_percent_is_not_treated_as_a_format_string() -> None:
    path = ROOT / "dicodePing_android/app/src/main/res/values/strings.xml"
    resources = ET.parse(path).getroot()
    node = next(item for item in resources if item.tag == "string" and item.attrib.get("name") == "splash_testing_sample")
    assert node.attrib.get("formatted") == "false"
    assert "30%" in "".join(node.itertext())


def test_android_validator_guards_literal_percent_regressions() -> None:
    source = (ROOT / "dicodePing_android/tools/validate_project.py").read_text(encoding="utf-8")
    assert "contains a literal % and must declare" in source
    assert 'node.attrib.get("formatted", "true").lower() != "false"' in source
