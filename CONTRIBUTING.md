# Contributing

1. Create a focused branch and keep unrelated changes separate.
2. Run `python tools/quality_gate.py`, `python -m compileall .`, and the unit tests.
3. For Android changes, run Gradle lint/tests/assembly.
4. Include a regression test for connection, parsing, lifecycle, or ranking changes.
5. Never commit profiles, subscription URLs, credentials, signing keys, generated build folders, or user logs.
