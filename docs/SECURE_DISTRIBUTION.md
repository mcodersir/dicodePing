# Desktop and Android distribution — RC4 legacy release hotfix

Desktop packages intentionally follow the same portable packaging model used by `v1.8.0-rc.4`:

- Windows: one-file EXE
- Linux: portable tar.gz
- macOS: DMG containing a `.app`

Only the Android release APK uses the owner's signing keystore. The desktop workflow does not require Windows, macOS, or Linux signing secrets.

All downloaded core archives are pinned by SHA-256. Xray is included in the desktop package; optional Aether and WARP/Usque archives are published as separate release assets.

Build all platform assets with:

```text
.github/workflows/v1.9.0-rc.4-release.yml
```

Build the Windows EXE locally with:

```bat
BUILD_RELEASE_RC4.bat
```

Build the signed Android APK with:

```bat
BUILD_SIGNED_APK_RC4.bat
```
