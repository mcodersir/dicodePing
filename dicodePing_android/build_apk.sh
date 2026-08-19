#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VERSION="3.0.0-pre.6"

command -v python >/dev/null 2>&1 || { echo "Python is required." >&2; exit 1; }
python ../tools/prepare_build_workspace.py --keep-outputs
python ../tools/validate_android_source_references.py
python ../tools/validate_android_release.py
python ../tools/prepare_vazirmatn.py --android

python ../tools/fetch_runtime_assets.py --android

chmod +x gradlew
./gradlew --no-daemon --warning-mode=fail clean testStandardDebugUnitTest lintStandardRelease assembleStandardRelease

mkdir -p release
APK="release/dicodePing-v${VERSION}-android.apk"
cp app/build/outputs/apk/standard/release/app-standard-release.apk "$APK"

# Fails the build if any connection core was omitted from the actual APK.
python tools/verify_apk_cores.py "$APK"
python tools/verify_apk_fonts.py "$APK"

echo "Built $APK"
