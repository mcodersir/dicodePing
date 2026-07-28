#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
./gradlew --no-daemon clean assembleStandardRelease
mkdir -p release
cp app/build/outputs/apk/standard/release/app-standard-release.apk   release/dicodePing-v1.9.0-rc.14-android.apk
echo "Built release/dicodePing-v1.9.0-rc.14-android.apk"
