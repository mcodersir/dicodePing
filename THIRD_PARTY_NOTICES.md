# Third-party notices

The original dicodePing source code is licensed under the repository's MIT
license. Release binaries also contain or dynamically use the components below;
those components remain under their own licenses.

## Native connection components

| Component | Version used by the build | License | Reproducible source / binary origin |
|---|---:|---|---|
| Xray-core | `v26.7.11` | MPL-2.0 | `XTLS/Xray-core`, tag `v26.7.11`; Windows assets are downloaded from that GitHub Release and checked against its companion `.dgst` SHA-256 record. |
| Wintun | `0.14.1` | GPL-2.0 | Official archive from `wintun.net`; archive SHA-256 is pinned in `dicodeping/constants.py`. Corresponding source is available from the `WireGuard/wintun` repository/tag. |
| AndroidLibXrayLite (`libv2ray`) | `26.7.11` | LGPL-3.0 | Official `2dust/AndroidLibXrayLite` Release `v26.7.11`; AAR SHA-256: `0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352`. |
| Aether | `1.4.0` | AGPL-3.0 | Bundled desktop executable from `CluvexStudio/Aether` Release `v1.4.0`; platform hashes are pinned in `assets/core-manifest.json`. Complete corresponding source: https://github.com/CluvexStudio/Aether/tree/v1.4.0 |
| Usque | `4.2.1` | MIT | Bundled desktop executable from `Diniboy1123/usque` Release `v4.2.1`; platform hashes are pinned in `assets/core-manifest.json`. |

## Design references (not copied or bundled)

- `MatinSenPai/Aether-GUI` (AGPL-3.0) was reviewed for documented interaction
  concepts such as Auto/Advanced profiles, transport selection and visible
  reconnect state. dicodePing contains an independent PySide6 implementation.
- `bepass-org/oblivion` (CC BY-NC-SA 4.0) was reviewed as a WARP UX reference.
  No Oblivion source code, artwork or application binary is included.
- `2dust/v2rayN` (GPL-3.0) was reviewed for public Xray client behavior. No
  v2rayN source or binary is included.
- `Jigsaw-Code/Intra` (Apache-2.0) informed the Secure DNS description. The
  implementation uses Xray's own DNS-over-HTTPS client; no Intra code is copied.
- `mcodersir/DicodeConfigChecker` (MIT) is the canonical public subscription
  source and scanner reference. dicodePing still requires a successful Xray
  HTTP probe and never promotes a TCP-only result.

The release workflow downloads the Android AAR instead of committing it. This
keeps the exact replaceable library artifact, application source, build scripts,
and version metadata available for relinking or rebuilding a modified library,
consistent with the LGPL combined-work requirements.

## Frameworks and libraries

- PySide6 / Qt for Python: LGPL-3.0, GPL, or applicable commercial terms.
- AndroidX, Material Components, and OkHttp: Apache-2.0.
- Python packages and Android dependencies are enumerated in the generated SPDX
  SBOM. Their upstream notices and license terms continue to apply.

## Included license texts

- [`licenses/MPL-2.0.txt`](licenses/MPL-2.0.txt)
- [`licenses/GPL-2.0.txt`](licenses/GPL-2.0.txt)
- [`licenses/LGPL-3.0.txt`](licenses/LGPL-3.0.txt)
- [`licenses/GPL-3.0.txt`](licenses/GPL-3.0.txt)
- [`licenses/AGPL-3.0.txt`](licenses/AGPL-3.0.txt)
- [`licenses/Apache-2.0.txt`](licenses/Apache-2.0.txt)

No private signing keys, credentials, or proprietary source are included in the
repository or Release assets.
## DicodeConfigChecker verification model

The RC10 scanner verification flow is adapted from the public `mcodersir/DicodeConfigChecker` project: supported configurations are tested by starting an Xray outbound and performing real HTTP traffic through it, while unsupported formats use a bounded TCP fallback. The RC10 implementation was rewritten for dicodePing's worker, cancellation, persistence and UI contracts.



## Aether Mobile integration reference
- Project: QW-AI-Code/Aether
- License: AGPL-3.0-or-later
- Use: Android native-engine build pipeline and lifecycle reference.

## Aether GUI integration reference
- Project: MatinSenPai/Aether-GUI
- License: AGPL-3.0-or-later
- Use: desktop lifecycle/state-machine design reference.

## defyxVPN architecture reference
- Project: UnboundTechCo/defyxVPN
- License: MIT
- Use: multi-core orchestration and one-tap UX reference; DXcore is not bundled.
## Vazirmatn

- Project: `rastikerdar/vazirmatn`
- Package: `vazirmatn@33.0.3`
- License: SIL Open Font License 1.1
- Use: Regular, Medium and Bold weights are fetched during release builds, verified against npm package integrity metadata and bundled inside the platform artifacts. Generated font files are not committed in the source snapshot.

