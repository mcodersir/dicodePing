# Vendored PyYAML runtime

This directory contains the pure-Python `yaml` package from **PyYAML 6.0.3**.
It is included only so the Windows one-click stable-release preflight can parse
GitHub Actions workflow YAML without requiring users to install an extra Python
package first.

- Upstream: https://github.com/yaml/pyyaml
- Version: 6.0.3
- License: MIT (see `LICENSE`)
- C extension: not bundled; the pure-Python loader is used.
