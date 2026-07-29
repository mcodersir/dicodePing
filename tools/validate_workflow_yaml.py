from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENDORED_PYYAML = ROOT / "tools" / "vendor" / "pyyaml"
EXPECTED_PYYAML_VERSION = "6.0.3"


def _load_yaml_module():
    # Prefer the repository-pinned pure-Python copy so release validation works
    # on a clean Windows Python installation with no third-party packages.
    sys.path.insert(0, str(VENDORED_PYYAML))
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - explicit diagnostic path
        raise RuntimeError(
            "Vendored PyYAML is missing or unreadable. Extract the complete release ZIP again."
        ) from exc
    version = getattr(yaml, "__version__", "")
    if version != EXPECTED_PYYAML_VERSION:
        raise RuntimeError(
            f"Unexpected vendored PyYAML version: {version or 'unknown'}; "
            f"expected {EXPECTED_PYYAML_VERSION}."
        )
    return yaml


def _strict_loader(yaml_module):
    class StrictWorkflowLoader(yaml_module.SafeLoader):
        pass

    def construct_mapping(loader, node, deep: bool = False):
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml_module.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise yaml_module.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    StrictWorkflowLoader.add_constructor(
        yaml_module.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping,
    )
    return StrictWorkflowLoader


def validate_workflow(path: Path, yaml_module, loader_type) -> None:
    text = path.read_text(encoding="utf-8-sig")
    if "\t" in text:
        raise ValueError(f"{path}: tab characters are not allowed in workflow YAML")
    document = yaml_module.load(text, Loader=loader_type)
    if not isinstance(document, dict):
        raise ValueError(f"{path}: workflow root must be a mapping")
    if "jobs" not in document or not isinstance(document["jobs"], dict) or not document["jobs"]:
        raise ValueError(f"{path}: workflow must define at least one job")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate every GitHub Actions workflow with the vendored PyYAML parser."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional workflow files. Defaults to .github/workflows/*.yml and *.yaml.",
    )
    args = parser.parse_args(argv)

    yaml_module = _load_yaml_module()
    loader_type = _strict_loader(yaml_module)
    paths = list(args.paths)
    if not paths:
        workflow_dir = ROOT / ".github" / "workflows"
        paths = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    if not paths:
        print("Workflow YAML validation failed: no workflow files were found.")
        return 1

    errors: list[str] = []
    for raw_path in paths:
        path = raw_path if raw_path.is_absolute() else ROOT / raw_path
        try:
            validate_workflow(path, yaml_module, loader_type)
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        print("Workflow YAML validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"Workflow YAML validation passed: {len(paths)} file(s), "
        f"vendored PyYAML {EXPECTED_PYYAML_VERSION}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
