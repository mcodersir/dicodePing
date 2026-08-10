# Secure distribution — Version 3

Release dependencies are pinned and verified before packaging. The local publisher does not require a `GH_TOKEN`; Git clone/push/tag operations use the authentication already configured for `git.exe`. The GitHub Actions release job uses the repository-scoped built-in GitHub Actions token. No authentication token is stored in source, release scripts, remotes, commits, logs or documentation.

Desktop release builds compile `dicodePing.CoreHost`, package pinned Xray and sing-box runtimes, and verify the CoreHost RPC handshake before artifact upload. Windows additionally packages Wintun where required. Android validates the pinned AndroidLibXrayLite AAR and all supported ABIs before accepting the universal APK.

The pre-release job only runs after all target jobs succeed. It verifies the expected artifact set, emits SHA-256 checksums, includes `LICENSE` and `THIRD_PARTY_NOTICES.md`, and publishes as a GitHub pre-release. Corresponding source for the GPL-covered sing-box binary is attached to the release as well.
