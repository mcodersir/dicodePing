# Control-plane request compatibility

Fox 5.0.1 uses v1.0.14 plus the browser fetch metadata change reviewed in upstream PR #79 (b1168ff72f654c4733c692c111fdc65c41e99b28).

The shared header helper sets Accept-Encoding: identity and Sec-Fetch-Dest: empty, Sec-Fetch-Mode: cors, Sec-Fetch-Site: same-site. Origin and Referer are set only for the exact Mozilla/Firefox domains and their subdomains. Challenge-page, PAT, OAuth, Guardian and other control-plane calls use the shared helper. Cookies are available for the account site, API root, auth endpoint and OAuth endpoint.

This prevents retrying an otherwise successful challenge with a different request fingerprint. It does not waive account verification or guarantee admission on every network. Never log passwords, bearer tokens, cookies or complete sign-in URLs.

Tests cover headers, origin scoping, cookie sharing, token refresh and challenge replay. A response from an invalid-token production probe demonstrates endpoint admission only; it does not demonstrate a successful real-account login.
