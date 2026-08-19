# dicodePing 3.0.0-pre.6 Project Validation Report

This archive is the complete Version 3 project source tree and release tooling package.

## Project package contents

- Desktop application/UI and product/business layer.
- Desktop CoreHost integration and vendored networking integration source.
- Android application and native runtime integration layer.
- Primary subscription integration and Scanner/profile logic.
- Windows, Linux, macOS arm64/x86_64 and Android build/package tooling.
- GitHub Actions CI, CodeQL and Version 3 pre-release workflow.
- Runtime version/checksum lock and runtime preparation/repair tooling.
- Licensing and third-party notices required by redistributed components.
- `PUBLISH_3.0.0_PRE1.bat` and `RELEASE_V3_PRERELEASE.bat` for the Version 3 pre-release workflow.

## Publisher behavior

The Windows publisher targets `mcodersir/dicodePing` directly and does **not** require a local `GH_TOKEN`. Git clone/push/tag operations use the authentication already configured for `git.exe`. If the project is already inside a clone of the target repository, the publisher preserves that checkout's `origin` transport, so an existing HTTPS/Git Credential Manager or SSH setup continues to be used.

The publisher clones the current default branch into a temporary checkout, then uses `tools/sync_release_tree.py` to replace the checkout from `SOURCE_MANIFEST.sha256`. The sync preserves only `.git`, verifies every source hash before and after copy, and ignores local runtime downloads, build outputs, caches and other files that are not part of the source manifest. It then validates the source and pushes the Version 3 commit to the default branch. The `v3.0.0-pre.6` tag is created only after source validation. `.github/workflows/release-v3.yml` then builds the four platform families and creates the pre-release with matching assets. `gh.exe` is optional and is used only to watch/verify the workflow when it is already installed and authenticated.

## GitHub Actions release hotfix

GitHub Actions run `31441422348` reached the platform jobs successfully, but all desktop builds stopped before packaging because `tools/build_windows.py`, `tools/build_linux.py`, and `tools/build_macos.py` imported `tools.build_desktop_common` while being executed as files. In that execution mode Python placed the `tools` directory, rather than the project root, at the front of `sys.path`, producing `ModuleNotFoundError: No module named 'tools'`.

The three desktop builders now bootstrap the project root for direct execution, and the release workflow invokes them with `python -m tools.build_*` as a second layer of protection. Release/CI workflow actions were also moved to Node 24 compatible majors. Regression tests cover both direct and module entrypoint modes.

## Validation performed

- V3 source validator passed.
- CoreHost/ServiceLib API surface validator passed.
- Android project validator passed.
- Android source-reference validator passed.
- Android release validator passed.
- Android Gradle Kotlin DSL validator passed.
- GitHub workflow YAML validator passed.
- 17 Python release tests passed.
- Python modules compile successfully.

## Release targets

- Windows x64
- Linux x86_64
- macOS arm64
- macOS x86_64
- Android universal APK

The Version 3 GitHub workflow creates the release only after all required platform jobs succeed and publishes it with the pre-release flag.
