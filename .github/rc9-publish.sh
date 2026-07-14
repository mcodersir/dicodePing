#!/bin/sh
set -e
mkdir -p a
gh run download "$RUN" -D a
gh release view "$TAG" >/dev/null 2>&1 || gh release create "$TAG" --prerelease -t "dicodePing $TAG"
find a -type f -exec gh release upload "$TAG" '{}' --clobber \;
