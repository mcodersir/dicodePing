dicodePing does not commit opaque native runtime binaries to source control.

The Windows build downloads these pinned upstream components over HTTPS:
- Xray-core v26.7.11 from XTLS/Xray-core, verified with the companion upstream SHA-256 digest file.
- Wintun v0.14.1 from wintun.net, verified against the SHA-256 value pinned in dicodeping/constants.py.

Run `python tools/prepare_core.py` before a manual PyInstaller build. The GitHub Actions release workflow performs this step automatically.
