from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_subscription_urls_are_normalized_before_okhttp_request_building() -> None:
    client = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/SubscriptionClient.kt")
    assert "internal fun normalizedSubscriptionHttpUrl" in client
    assert 'else -> "https://$value"' in client
    assert 'val httpUrl = normalizedSubscriptionHttpUrl(url) ?: return@withContext ""' in client
    assert ".url(httpUrl)" in client
    assert 'Request.Builder().url(url)' not in client


def test_android_release_version_is_rc15_and_install_is_forced_by_version_code() -> None:
    gradle = read("dicodePing_android/app/build.gradle.kts")
    assert 'versionCode = 50' in gradle
    assert 'versionName = "1.9.0-rc.15"' in gradle
    assert 'buildConfigField("String", "RELEASE_VERSION", "\\"1.9.0-rc.15\\"")' in gradle


def test_apk_build_cannot_skip_aether_usque_or_final_apk_verification() -> None:
    build = read("dicodePing_android/build_apk.sh")
    workflow = read(".github/workflows/release.yml")
    verifier = read("dicodePing_android/tools/verify_apk_cores.py")
    gradle = read("dicodePing_android/app/build.gradle.kts")

    assert "python tools/prepare_bundled_cores.py" in build
    assert "testStandardDebugUnitTest" in build
    assert 'python tools/verify_apk_cores.py "$APK"' in build
    assert "./build_apk.sh" in workflow
    for abi in ("arm64-v8a", "x86_64"):
        for lib in ("libgojni.so", "libaether.so", "libusque.so"):
            assert f"lib/$abi/{lib}" in workflow
    assert 'MANIFEST = "assets/bundled_cores.json"' in verifier
    assert 'sourceSets.getByName("main").jniLibs.srcDir("src/main/jniLibs")' in gradle
    assert "jniLibs.useLegacyPackaging = true" in gradle


def test_external_core_runtime_reads_from_extracted_native_library_directory() -> None:
    process = read(
        "dicodePing_android/app/src/main/java/ir/dicode/ping/core/AndroidExternalCoreProcess.kt"
    )
    manifest = read("dicodePing_android/app/src/main/AndroidManifest.xml")
    assert "context.applicationInfo.nativeLibraryDir" in process
    assert 'android:extractNativeLibs="true"' in manifest


def test_rc14_empty_source_settings_are_repaired_before_background_update_checks() -> None:
    settings = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/SettingsStore.kt")
    assert "normalizedSubscriptionHttpUrl(current.url) == null" in settings
    assert "list[defaultIndex] = defaultSource(language)" in settings
    assert "if (repaired) saveSources(list)" in settings



def test_dirty_old_workspace_tethering_copy_is_cleaned(tmp_path) -> None:
    from tools.prepare_build_workspace import clean

    relative = Path("dicodePing_android/app/src")
    main = relative / "main/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
    standard = relative / "standard/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
    rooted = relative / "rooted/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
    for path in (main, standard, rooted):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("package ir.dicode.ping.vpn\nclass AndroidTetheringController\n", encoding="utf-8")

    removed = clean(tmp_path, clean_outputs=False)

    assert tmp_path / main in removed
    assert not (tmp_path / main).exists()
    assert (tmp_path / standard).is_file()
    assert (tmp_path / rooted).is_file()


def test_rc15_deploy_and_local_apk_build_purge_stale_tethering_class() -> None:
    deploy = read("DEPLOY_PRERELEASE_RC15.bat")
    build_sh = read("dicodePing_android/build_apk.sh")
    build_bat = read("dicodePing_android/build_apk.bat")
    stale = "dicodePing_android\\app\\src\\main\\java\\ir\\dicode\\ping\\vpn\\AndroidTetheringController.kt"

    assert stale in deploy
    assert 'del /f /q "%STALE_TETHER_CONTROLLER%"' in deploy
    assert "python ../tools/prepare_build_workspace.py --keep-outputs" in build_sh
    assert "py -3 ..\\tools\\prepare_build_workspace.py --keep-outputs" in build_bat
