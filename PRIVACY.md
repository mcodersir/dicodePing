# Privacy

The client should process profiles locally and must not collect browsing history, DNS queries, device identifiers, crash logs, or connection metadata unless the user explicitly opts in. Any future telemetry requires a documented schema, retention period, purpose, endpoint, and an off-by-default control.

Subscription URLs and proxy credentials are secrets. Logs must redact user info, UUIDs, passwords, tokens, query strings, and full server links.
