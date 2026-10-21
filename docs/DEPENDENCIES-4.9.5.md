# Dependency review — 4.9.5

Checked against release/tag APIs and Maven Central/Google Maven/NuGet metadata on 2026-10-21. Machine-readable direct-package inventories: [Android](ANDROID-DEPENDENCIES-4.9.5-audit.json), [desktop](DEPENDENCIES-4.9.5-audit.json). Their `current` column is the 4.9.4 input; `latest` is a candidate, not a statement that every candidate is compatible. Final versions are the committed manifests and `scripts/runtime-pins-4.9.5.json`.

| Component | Selected | Change / decision |
|---|---|---|
| Xray | 26.10.19 | Updated desktop archives and source-built Android library; immutable archive hashes and native commit recorded |
| Android native source | e262d9f041e92a184011067c840ffaed070e18ee | P67 reference; Dicode HTTP health validation patch retained and tested |
| HEV | 2.19.1 / 107a5083cb33d729a476c8282745dfc2f12e48e2 | New compact-packet and receive-window fixes; source built for all APK ABIs |
| Fox | Dicode 4.9.5 / reference 1.0.7 | Shared Go source, TLS fragmentation/control bootstrap/multiple HTTP2 carriers |
| sing-box / mihomo / Aether | 1.14.3 / 1.19.32 / 2.3.0 | Already latest verified stable; retained, not downgraded or replaced by development snapshots |
| Go | 1.27.3 | Updated build patch version, including mobile bindings builder |
| .NET | Latest 10.0.x SDK/runtime patch | Local SDK 10.0.402; release uses setup-dotnet 10.0.x and self-contained runtimes |
| Java | 27 | Build JDK updated; Gradle 9.8 supports it. Android bytecode compatibility and minSdk 29 retained |
| Kotlin / Gradle / AGP | 2.4.21 / 9.8.2 / 9.4.1 | Kotlin/Gradle updated; AGP already current stable |
| Python | 3.15 | CI/release scripts use current stable Python; scripts use only standard library, no application Python package stack to update |
| MMKV | 2.4.3 | Storage library update; installation/upgrade checks preserve app identity and saved data |
| Avalonia | 12.1.4 | UI runtime patch update; DataGrid/Semi/Edit kept at their separately published compatible versions |
| ReactiveUI / UI bridge / generator | 24.3.0 / 12.1.2 / 4.2.0 | Updated compatible set; generator now explicitly receives compile assets |
| Downloader / QRCoder / NLog | 5.10.1 / 1.8.1 / 6.2.2 | Stable updates |
| SQLite wrapper native bundle | 3.54.1 | Updated SQLite package |
| Assertions / Test SDK / xUnit | 9.6.0 / 18.11.0 / 3.2.2 (runner 3.1.5) | Compatible VSTest dependency updates; xUnit 4 requires a separate MTP runner migration |
| ProtectedData | 10.0.13 | .NET security patch package |
| Routing databases | Desktop 202610202206; Android 202610210934; CN/private 202610190920 | Explicit checksums, no unverified latest downloads |

## Compatibility exceptions

- ReactiveUI 26.0.1 moves activation/view interfaces to a different assembly/API. The Avalonia 12 bridge 12.1.2 still targets the 24.x interface. The attempted 26.x build exposed missing `IViewFor`/`IActivatableView` references; 24.3.0 is retained as the updated compatible release. Numerically larger bridge 14.7.1 is an older Avalonia 11-era package, not a newer compatible bridge.
- Avalonia 12.1.4 depends on SkiaSharp native ABI 3.119.4. SkiaSharp 4.x and ZXing Skia bindings 0.16.24 require ABI 4.x. Keep native assets 3.119.4 and bindings 0.16.22 together; do not mix managed/native Skia major versions.
- The vendored GlobalHotKeys example/test projects are not product builds. Their legacy demonstration UI stack is not migrated to a different UI major version as a dependency-only operation.
- Conscrypt 2.8.0 is available upstream, but this application does not bundle a Conscrypt artifact. Android's system Conscrypt is maintained by Android/system updates; the Fox helper uses Go TLS. Adding an unused provider does not update the OS security module or improve this tunnel.

APK version name/code, supported ABIs, signing certificate, native ELF presence, HTTP endpoint validation, core configuration acceptance and real local proxy traffic are release gates. No upstream account credentials are available for a multi-hour Mozilla production session test.
