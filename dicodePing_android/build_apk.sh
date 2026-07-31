#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VERSION="2.0.5"
CORE_VERSION="26.7.11"
CORE_SHA256="0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352"
CORE_AAR="local-maven/ir/dicode/local/libv2ray/${CORE_VERSION}/libv2ray-${CORE_VERSION}.aar"
CORE_URL="https://github.com/2dust/AndroidLibXrayLite/releases/download/v${CORE_VERSION}/libv2ray.aar"

command -v python >/dev/null 2>&1 || { echo "Python is required." >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 1; }

# Remove stale files left when this ZIP was extracted over an older RC.
python ../tools/prepare_build_workspace.py --keep-outputs
python ../tools/validate_android_source_references.py
python ../tools/validate_android_lint_hotfix.py
python ../tools/prepare_vazirmatn.py --android

# This is intentionally part of the build command itself. A release APK can no
# longer be assembled unless Aether and Usque have first been prepared for all
# supported 64-bit ABIs.
python tools/prepare_bundled_cores.py

mkdir -p "$(dirname "$CORE_AAR")"
if [ ! -s "$CORE_AAR" ] || ! echo "$CORE_SHA256  $CORE_AAR" | sha256sum --check --strict >/dev/null 2>&1; then
  rm -f "$CORE_AAR"
  curl --fail --location --retry 4 --retry-delay 2 --output "$CORE_AAR" "$CORE_URL"
fi
echo "$CORE_SHA256  $CORE_AAR" | sha256sum --check --strict

chmod +x gradlew
./gradlew --no-daemon --warning-mode=fail clean testStandardDebugUnitTest lintStandardRelease assembleStandardRelease

mkdir -p release
APK="release/dicodePing-v${VERSION}-android.apk"
cp app/build/outputs/apk/standard/release/app-standard-release.apk "$APK"

# Fails the build if any connection core was omitted from the actual APK.
python tools/verify_apk_cores.py "$APK"
python tools/verify_apk_fonts.py "$APK"

echo "Built $APK"
