from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt"


def main() -> int:
    errors: list[str] = []
    source = SCANNER.read_text(encoding="utf-8")

    # ScannerCoordinator owns the repository as `repo`. RC17 accidentally used
    # `repository` here, which passed text-only tests but failed Kotlin CI.
    if "repository.settings.resourceMode" in source:
        errors.append(
            "ScannerCoordinator references undefined `repository`; use `repo.settings.resourceMode`."
        )
    if "private val repo = AppRepository.get(context)" not in source:
        errors.append("ScannerCoordinator repository field `repo` is missing.")
    if "RuntimeTuning.detect(context, repo.settings.resourceMode)" not in source:
        errors.append("ScannerCoordinator runtime tuning is not wired to repo.settings.resourceMode.")

    if errors:
        print("Android source-reference validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Android source-reference validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
