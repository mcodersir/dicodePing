# Third-party notices — dicodePing 3

This file records third-party code/runtime components used by dicodePing Version 3. Product branding, UI, subscription ownership, and dicodePing-specific business logic remain dicodePing-specific; third-party provenance is not removed or misrepresented.

## 2dust/v2rayN ServiceLib — 7.24.5

- Upstream: `https://github.com/2dust/v2rayN`
- License: GNU GPL v3
- Use in V3: selected ServiceLib networking/client architecture is compiled into `dicodePing.CoreHost`; the upstream UI is not used.
- Corresponding vendored source: `third_party/network-engine/runtime/`
- Upstream license: `third_party/network-engine/LICENSE`

The V3 desktop combined distribution is provided under GPL-3.0. An existing MIT notice covering product-authored portions is retained at `licenses/PRODUCT_MIT_NOTICE.txt`; retaining that notice does not keep an alternate networking implementation in the product.

## XTLS/Xray-core — 26.7.11

- Upstream: `https://github.com/XTLS/Xray-core`
- License: Mozilla Public License 2.0
- Use: desktop core executable downloaded by the reproducible build helper; Android receives Xray through its platform bridge.
- License copy: `licenses/MPL-2.0.txt`

## SagerNet/sing-box — 1.13.12

- Upstream: `https://github.com/SagerNet/sing-box`
- License: GPL-3.0-or-later, with the upstream additional naming/association notice retained by upstream.
- Use: desktop runtime for profile/TUN paths selected by the ServiceLib integration.
- Release binaries are downloaded from the exact upstream release and verified against the upstream checksums file.
- GPL text: `licenses/GPL-3.0.txt`

## Wintun — 0.14.1

- Upstream: `https://www.wintun.net/`
- License: GPL-2.0, with upstream redistribution terms applying.
- Use: Windows TUN driver component.
- License copy: `licenses/GPL-2.0.txt`

## 2dust/AndroidLibXrayLite — 26.7.11

- Upstream: `https://github.com/2dust/AndroidLibXrayLite`
- Use: Android native VPN/core bridge distributed as the pinned `libv2ray.aar` release artifact.
- The exact AAR URL and SHA-256 are pinned in `dicodePing_android/app/build.gradle.kts` and the Android build scripts.
- Its upstream notices/license and notices of its bundled dependencies remain applicable.

## PySide6 / Qt for Python

Desktop UI uses PySide6. Qt/PySide redistribution must comply with the licenses applicable to the binary packages used for a release.

## Vazirmatn

The project prepares Vazirmatn font assets through its existing build tooling. Preserve the font project's license when distributing those files.

## Source availability

This source package includes the modified/adapted ServiceLib source used by the desktop runtime. Build scripts fetch runtime binaries from their pinned upstream release locations. Keep this file and all license files with redistributed release artifacts.
