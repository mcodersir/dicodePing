from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADLE_FILE = ROOT / "dicodePing_android" / "app" / "build.gradle.kts"
EXPECTED = 'Regex("""jni/.+/(libgojni|libv2ray)\\.so""")'
INVALID = 'Regex("jni/.+/(libgojni|libv2ray)\\.so")'


def main() -> int:
    text = GRADLE_FILE.read_text(encoding="utf-8")
    if INVALID in text:
        raise SystemExit(
            "Invalid Kotlin string escape found in Android build script: use a raw "
            "triple-quoted Regex string or escape the backslash twice."
        )
    if EXPECTED not in text:
        raise SystemExit(
            "Expected Android native-library validation Regex is missing from "
            f"{GRADLE_FILE.relative_to(ROOT)}"
        )
    print("Android Gradle Kotlin DSL regex validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
