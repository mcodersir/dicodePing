#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
CORE="$PWD/local-maven/ir/dicode/local/libv2ray/26.6.2/libv2ray-26.6.2.aar"
if [ ! -f "$CORE" ]; then
  echo "Missing Android core." >&2
  echo "Download: https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.6.2/libv2ray.aar" >&2
  echo "Rename to libv2ray-26.6.2.aar and place at: $CORE" >&2
  exit 1
fi
./gradlew --no-daemon clean :app:assembleDebug
mkdir -p release
cp app/build/outputs/apk/debug/app-debug.apk release/dicodePing-v0.1.2-android-debug.apk
echo "APK: release/dicodePing-v0.1.2-android-debug.apk"
