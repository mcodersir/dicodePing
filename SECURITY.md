# Security policy

Please report vulnerabilities privately to the repository maintainers. Do not include live subscription URLs, UUIDs, credentials, private keys, or user traffic logs in public issues.

Supported releases are the latest tagged release and the current default branch. Reports should include affected version/commit, platform, reproduction steps, expected impact, and sanitized logs.

## Release verification

Every release must publish `SHA256SUMS`, `SBOM.spdx.json`, the source commit ID, and a GitHub artifact attestation. A checksum proves integrity only when obtained from a trusted channel; it is not a substitute for a maintainer signature or platform attestation.
