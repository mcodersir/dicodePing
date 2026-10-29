#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd "$(dirname "$0")/.." && pwd)
native_root="$project_root/native-upstream/AndroidLibXrayLite"
git -C "$native_root" fetch --depth 1 origin 3be30ae8c718a6ff38bd569993860d25908595e8
git -C "$native_root" checkout --detach FETCH_HEAD
test "$(git -C "$native_root" rev-parse HEAD)" = 3be30ae8c718a6ff38bd569993860d25908595e8
git -C "$native_root" apply --check "$project_root/scripts/patches/android-core-health.patch"
git -C "$native_root" apply "$project_root/scripts/patches/android-core-health.patch"
cp "$project_root/scripts/patches/libv2ray_dicode_health_test.go.txt" "$native_root/libv2ray_dicode_health_test.go"
# The source-built AAR has no pre-generated Geo assets. Bundle the files
# referenced by default/user routing in the APK; native Xray can read APK assets
# directly, including before the UI has copied them into the user asset folder.
python "$project_root/scripts/stage-android-geodata.py"
cd "$native_root"
go mod edit -replace=github.com/xtls/xray-core=github.com/patterniha/xray-core@e5acafbbaa5c1bc279ac40ebcb9f204dc7f8dce5
go mod tidy
go test -timeout 120s ./...
# Match the module's pinned mobile bindings instead of installing an unbounded latest tool.
go install golang.org/x/mobile/cmd/gomobile@v0.0.0-20261011034528-197770444867
export PATH="$(go env GOPATH)/bin:$PATH"
gomobile init
mkdir -p "$project_root/apps/android/app/libs"
gomobile bind -target=android/arm,android/arm64,android/386,android/amd64 -androidapi 29 -trimpath \
    -ldflags='-s -w -buildid= -checklinkname=0' -o "$project_root/apps/android/app/libs/libv2ray.aar" ./
sha256sum "$project_root/apps/android/app/libs/libv2ray.aar"
