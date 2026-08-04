from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_release_lint_keeps_errors_fatal_without_promoting_advisories() -> None:
    gradle = text("dicodePing_android/app/build.gradle.kts")
    assert "abortOnError = true" in gradle
    assert "warningsAsErrors = false" in gradle
    assert "ignoreWarnings = false" in gradle
    assert 'lintConfig = file("lint.xml")' in gradle
    assert "lintStandardRelease" in text("dicodePing_android/build_apk.sh")


def test_runtime_language_and_font_compatibility() -> None:
    gradle = text("dicodePing_android/app/build.gradle.kts")
    assert "enableSplit = false" in gradle
    family = text("dicodePing_android/app/src/main/res/font/vazirmatn.xml")
    assert "app:fontWeight" in family
    assert "android:fontWeight" not in family


def test_manifest_visibility_and_backup_rules() -> None:
    manifest = text("dicodePing_android/app/src/main/AndroidManifest.xml")
    assert "<queries>" in manifest
    assert "android.intent.category.LAUNCHER" in manifest
    assert "android:dataExtractionRules" in manifest
    assert "android:enableOnBackInvokedCallback" not in manifest
    assert (ROOT / "dicodePing_android/app/src/main/res/xml/data_extraction_rules.xml").is_file()


def test_known_blocking_lint_regressions_are_fixed_or_scoped() -> None:
    source_adapter = text("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/SourceAdapter.kt")
    assert "DiffUtil.calculateDiff" in source_adapter
    assert "notifyDataSetChanged" not in source_adapter
    volume = text("dicodePing_android/app/src/main/java/ir/dicode/ping/net/VolumeDetector.kt")
    assert 'String.format(Locale.US, "%.1f GB"' in volume
    scanner = text("dicodePing_android/app/src/main/res/layout/fragment_scanner.xml")
    assert 'tools:ignore="NestedScrolling"' in scanner
    item = text("dicodePing_android/app/src/main/res/layout/item_source.xml")
    assert "MaterialSwitch" in item
    assert "<Switch" not in item


def test_typography_stage_labels_are_lint_safe() -> None:
    strings = text("dicodePing_android/app/src/main/res/values/strings.xml")
    assert "1/3" not in strings
    assert "2/3" not in strings
    assert "3/3" not in strings


def test_downloadable_font_certificates_are_not_shipped() -> None:
    assert not (ROOT / "dicodePing_android/app/src/main/res/values/font_certs.xml").exists()
    assert not (ROOT / "dicodePing_android/app/src/main/res/values-v26/font_certs.xml").exists()

def test_apple_http_probe_is_allowed_only_for_its_domain() -> None:
    policy = text("dicodePing_android/app/src/main/res/xml/network_security_config.xml")
    assert '<base-config cleartextTrafficPermitted="false">' in policy
    assert '<domain-config cleartextTrafficPermitted="true">' in policy
    assert '<domain includeSubdomains="false">captive.apple.com</domain>' in policy

def test_ping_probe_timeout_is_compatible_with_android_api_24() -> None:
    probe = text("dicodePing_android/app/src/main/java/ir/dicode/ping/net/PingProbe.kt")
    assert "process.waitFor(ICMP_DEADLINE_MS, TimeUnit.MILLISECONDS)" not in probe
    assert "private fun waitForExit" in probe
    assert "process.exitValue()" in probe
    assert "process.destroy()" in probe
    assert "Build.VERSION.SDK_INT >= Build.VERSION_CODES.O" in probe
    assert "process.destroyForcibly()" in probe
    assert "@SuppressLint(\"NewApi\")" not in probe


def test_persian_resources_do_not_duplicate_nontranslatable_constants() -> None:
    localized = text("dicodePing_android/app/src/main/res/values-fa/strings.xml")
    assert 'translatable="false"' not in localized
    for name in (
        "brand_name",
        "brand_handle",
        "brand_initial",
        "status_dot_symbol",
        "world_symbol",
        "scanner_sub_name",
    ):
        assert f'name="{name}"' not in localized

def test_android_project_validator_allows_base_nontranslatable_fallback() -> None:
    validator = text("dicodePing_android/tools/validate_project.py")
    assert "base_nontranslatable" in validator
    assert "expected_fa = base - base_nontranslatable" in validator
    assert "base-only-translatable" in validator
