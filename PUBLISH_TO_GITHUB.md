# Publish dicodePing

Target: public repository `mcodersir/dicodePing`.

## Repository bootstrap

Run from this clean checkout with an authenticated GitHub CLI session:

```bash
gh repo create mcodersir/dicodePing \
  --public \
  --description "Fast open-source Xray client for Windows and Android with real outbound health checks" \
  --source . \
  --remote origin \
  --push

gh repo edit mcodersir/dicodePing \
  --homepage "https://mcodersir.github.io/dicodePing/" \
  --add-topic android \
  --add-topic windows \
  --add-topic xray \
  --add-topic vpn \
  --add-topic kotlin \
  --add-topic pyside6
```

The root workflows are the source of truth:

- `ci.yml`: Python checks, security gate, Android lint/tests/debug build
- `codeql.yml`: Python and Java/Kotlin CodeQL analysis
- `release.yml`: tagged Windows/Android builds and GitHub Release publication
- `docs.yml`: GitHub Pages documentation deployment

## Release

The signed local tag is `v0.1.2`. Push it only after the `main` branch exists remotely:

```bash
git push origin v0.1.2
```

That tag triggers the Release workflow. The workflow, not a local upload, creates the EXE, APKs, checksums, SPDX SBOM, license bundle, and attestations.

For a new repository, set **Settings → Pages → Build and deployment → Source** to **GitHub Actions** once so `docs.yml` can publish the documentation landing page.
