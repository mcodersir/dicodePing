# 5.0.3 preparation — NOT RELEASED

Base: v5.0.2 (21a15d8d6c7bec36f75e9b180158c3dd5d7c168e).

## Confirmed source defect

Android AppLocaleManager replaced explicit Chinese and system-language choices with Persian in selection, persisted preference restoration, and Android 13 locale migration. Removed these coercions. System language now uses an empty locale list rather than dereferencing a null Locale. Added an instrumented regression test for preference preservation. Runtime verification is pending.

## Evidence limits

The supplied DicodePing-diagnostics-20261109-223250(1).zip identifies Windows 4.9.991, not Android 5.0.2. Its three log files contain 87 net_http_connect_timedout messages and no FwpmTransactionCommit0 message. The separately quoted WFP failure prevents Xray TUN startup; a numeric WFP error, core version, and isolated Windows reproduction are needed to identify the faulty object lifetime. Disabling strict-route leak protection is not a verified correction.

## Original acceptance checklist (see RELEASE-5.0.3.md and CI for current status)

- Reproduce and correct Windows WFP object lifecycle with leak protection retained.
- Verify Android Fox socket protection, upstream recovery and measured throughput on a device.
- Version-scoped first-launch language/theme selection on Android and desktop.
- Complete and review all requested locale resources, including hardcoded UI strings.
- Represent unlimited allowance only when known from provider policy/API; a quota retrieval error must retain last known allowance and identify it as stale.
- Responsive UI and structured, redacted connection diagnostics.
- Build, sign, install/upgrade, and smoke-test all release artifacts before publishing 5.0.3.

Local validation: git diff --check passed. Android Gradle wrapper could not download Gradle 9.8.2: java.net.SocketException: Network is unreachable. No Android or Windows runtime validation was performed.

## Desktop recovery regression reproduced

The latest pasted 500-line excerpt contains successful subscription fetches and Xray accepted-client messages, with no Fox helper loss/recovery messages. It does not locate the user's reported outage.

Independently, the existing pool only retired sessions after another client open, even when the session's keepalive had already marked it dead. Reproduction commit 225ae6d failed `TestPoolRestoresDeadIdleSlotWithoutAClientRequest` on Linux CI run 43034102935 after 2.01s, with no client request triggering replacement. The correction monitors existing liveness state every 500ms, does not probe or churn live sessions, and replenishes dead slots proactively. Retry delay starts at 500ms, grows exponentially and caps at 10s; slots are staggered. Added tests cover idle recovery, retry bounds, keeping healthy sessions, and stopping recovery on explicit close. User-network runtime confirmation remains separate from these controlled tests.
