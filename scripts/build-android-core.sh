#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd "$(dirname "$0")/.." && pwd)
native_root="$project_root/native-upstream/AndroidLibXrayLite"
test "$(git -C "$native_root" rev-parse HEAD)" = cb1983ac21ff8e7724708dc850c574a339e6241b
git -C "$native_root" apply --check "$project_root/scripts/patches/android-core-health.patch"
git -C "$native_root" apply "$project_root/scripts/patches/android-core-health.patch"
cp "$project_root/scripts/patches/libv2ray_dicode_health_test.go.txt" "$native_root/libv2ray_dicode_health_test.go"
cd "$native_root"
go test -timeout 120s ./...
# Match the module's pinned mobile bindings instead of installing an unbounded latest tool.
go install golang.org/x/mobile/cmd/gomobile@v0.0.0-20260908204917-8b95e45f8d3e
export PATH="$(go env GOPATH)/bin:$PATH"
gomobile init
mkdir -p "$project_root/apps/android/app/libs"
gomobile bind -target=android/arm,android/arm64,android/386,android/amd64 -androidapi 29 -trimpath \
    -ldflags='-s -w -buildid= -checklinkname=0' -o "$project_root/apps/android/app/libs/libv2ray.aar" ./
sha256sum "$project_root/apps/android/app/libs/libv2ray.aar"
