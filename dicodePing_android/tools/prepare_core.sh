#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$ROOT/local-maven/ir/dicode/local/libv2ray/26.7.11/libv2ray-26.7.11.aar"
SOURCE="${1:-$HOME/Downloads/libv2ray.aar}"

if [ ! -f "$SOURCE" ]; then
  echo "Core file not found: $SOURCE" >&2
  echo "Download: https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.7.11/libv2ray.aar" >&2
  echo "Place it at: $TARGET" >&2
  exit 1
fi

EXPECTED="0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352"
printf '%s  %s\n' "$EXPECTED" "$SOURCE" | sha256sum --check --strict
mkdir -p "$(dirname "$TARGET")"
cp -f "$SOURCE" "$TARGET"
echo "Android core verified and installed: $TARGET"
