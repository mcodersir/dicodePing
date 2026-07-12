# Architecture

## Connection pipeline

1. Parse and validate server/subscription input; reject oversized or malformed data.
2. Resolve candidates with bounded DNS and TCP pre-checks.
3. Build one isolated Xray configuration per candidate.
4. Start the core with a unique local port and cancellation token.
5. Measure HTTPS through that candidate's local SOCKS5 endpoint.
6. Rank successful candidates by median latency plus jitter penalty.
7. Connect the winner; if the post-connect health check fails, stop it and try the next successful candidate.
8. Publish state changes through a single state machine: Disconnected, Preparing, Connecting, Connected, Reconnecting, Stopping, Failed.

## UI performance

Network, parsing, filesystem, process waiting, and hashing work must never run on the Qt or Android main thread. UI updates are coalesced and animations should use platform property animators rather than timer loops. Cancellation and disposal are mandatory when a window/activity/service is destroyed.

## Security boundaries

Subscription content is untrusted input. Core configuration, URLs, filenames, ports, and process arguments are validated. TLS verification remains enabled. Bundled executables are never executed during audit; release binaries need provenance, hashes, licenses, SBOM, and attestation.
