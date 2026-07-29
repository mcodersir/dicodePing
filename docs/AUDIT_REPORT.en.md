# dicodePing Technical and Security Audit

Review date: **2026-07-12**
Version: **0.1.2**

## Scope

The review covers the Windows and Android source trees, subscription ingestion, connectivity measurement, Xray lifecycle, VPN/TUN routing, UI execution boundaries, supply-chain controls, and CI/release workflows. Unknown binaries from the supplied archive were not executed and are not committed to the public source tree.

## Result

- 27 unit and maintenance tests pass.
- The security quality gate completes with no errors or warnings.
- 52 Android XML/manifest files and parity across 125 Persian/English localized resources validate successfully.
- Final profile eligibility requires a request through the real SOCKS/Xray path; bounded TCP probing is only a pre-check.
- Android captures both IPv4 and IPv6 default routes, closing the direct IPv6 bypass class.
- The Windows icon is applied in the executable resource, Qt application layer, stable `AppUserModelID`, and native small/large HWND icon slots.
- Native cores are not committed as opaque source artifacts. Workflows fetch fixed upstream versions and verify SHA-256 before packaging.
- Tagged releases include checksums, an SPDX SBOM, third-party notices, license texts, and GitHub artifact attestations.

## Stated boundary

Static analysis and unit tests do not replace execution on Windows 10/11 or physical Android devices. GitHub Actions is the authoritative binary build path, and the real-device acceptance matrix is documented in [`TEST_MATRIX.md`](TEST_MATRIX.md).
