# Version 3 native runtime cache

Version 3 uses pinned native runtimes. Exact versions and fixed hashes are recorded in `RUNTIME_ASSETS.lock.json`. `tools/fetch_runtime_assets.py` downloads and verifies the exact archives needed by release builds. Build helpers prefer verified files in this directory and only fetch a missing asset.

Prepare all targets:

```bat
PREPARE_V3_RUNTIME.bat
```

Or:

```bash
python tools/fetch_runtime_assets.py
```

Pinned desktop payloads:

- Xray 26.7.11 — Windows x64, Linux x64, macOS arm64, macOS x64
- sing-box 1.13.12 — Windows amd64, Linux amd64, Darwin arm64, Darwin amd64
- Wintun 0.14.1 — Windows

The Android runtime is installed into `dicodePing_android/local-maven/` by the same helper. Every pinned payload is verified before release packaging. For sing-box 1.13.12, the four SHA-256 values are pinned directly from GitHub release-asset digest metadata; that release does not provide a standalone `*-checksums.txt` file. Licensing and source-provenance material is in `THIRD_PARTY_NOTICES.md` and `licenses/`.
