#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
CORE="$PWD/local-maven/ir/dicode/local/libv2ray/26.7.11/libv2ray-26.7.11.aar"
if [[ ! -f "$CORE" ]]; then
  echo "Missing verified Android core: $CORE" >&2
  echo "Run tools/prepare_core.sh after downloading the pinned upstream AAR." >&2
  exit 1
fi
for name in ANDROID_KEYSTORE_PATH ANDROID_KEYSTORE_PASSWORD ANDROID_KEY_ALIAS ANDROID_KEY_PASSWORD; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing APK signing variable: $name" >&2
    exit 1
  fi
done
chmod +x gradlew
./gradlew --no-daemon clean lintStandardRelease testStandardReleaseUnitTest assembleStandardRelease
mkdir -p release
APK="release/dicodePing-v1.9.0-rc.11-android.apk"
cp app/build/outputs/apk/standard/release/app-standard-release.apk "$APK"
if [[ -n "${ANDROID_HOME:-}" ]]; then
  APKSIGNER="$ANDROID_HOME/build-tools/$(ls "$ANDROID_HOME/build-tools" 2>/dev/null | sort -V | tail -1)/apksigner"
  if [[ -x "$APKSIGNER" ]]; then
    "$APKSIGNER" verify --verbose --print-certs "$APK"
  fi
fi
sha256sum "$APK" > "$APK.sha256"
echo "Signed Android APK created: $PWD/$APK"
