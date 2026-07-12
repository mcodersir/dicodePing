# Third-party notices

The original dicodePing source code is licensed under the repository's MIT
license. Release binaries also contain or dynamically use the components below;
those components remain under their own licenses.

## Native connection components

| Component | Version used by the build | License | Reproducible source / binary origin |
|---|---:|---|---|
| Xray-core | `v26.7.11` | MPL-2.0 | `XTLS/Xray-core`, tag `v26.7.11`; Windows assets are downloaded from that GitHub Release and checked against its companion `.dgst` SHA-256 record. |
| Wintun | `0.14.1` | GPL-2.0 | Official archive from `wintun.net`; archive SHA-256 is pinned in `dicodeping/constants.py`. Corresponding source is available from the `WireGuard/wintun` repository/tag. |
| AndroidLibXrayLite (`libv2ray`) | `26.6.2` | LGPL-3.0 | Official `2dust/AndroidLibXrayLite` Release `v26.6.2`; AAR SHA-256: `367d6b2f74e62c974c61210c56802127812be4c9410a83a6b8b6cac765a7595e`. |

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
- [`licenses/Apache-2.0.txt`](licenses/Apache-2.0.txt)

No private signing keys, credentials, or proprietary source are included in the
repository or Release assets.
