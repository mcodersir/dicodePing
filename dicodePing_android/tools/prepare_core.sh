#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$ROOT/local-maven/ir/dicode/local/libv2ray/26.6.2/libv2ray-26.6.2.aar"
SOURCE="${1:-$HOME/Downloads/libv2ray.aar}"

if [ ! -f "$SOURCE" ]; then
  echo "Core file not found: $SOURCE" >&2
  echo "Download: https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.6.2/libv2ray.aar" >&2
  echo "Place it at: $TARGET" >&2
  exit 1
fi

EXPECTED="367d6b2f74e62c974c61210c56802127812be4c9410a83a6b8b6cac765a7595e"
printf '%s  %s\n' "$EXPECTED" "$SOURCE" | sha256sum --check --strict
mkdir -p "$(dirname "$TARGET")"
cp -f "$SOURCE" "$TARGET"
echo "Android core verified and installed: $TARGET"
