import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipFile

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val coreVersion = "26.7.11"
val coreSha256 = "0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352"
val coreAar = rootProject.file(
    "local-maven/ir/dicode/local/libv2ray/$coreVersion/libv2ray-$coreVersion.aar"
)
// CodeQL needs Kotlin/Java bytecode, not a runnable APK. Native runtime helpers
// are still mandatory for every normal/debug/release build and can only be
// skipped by the dedicated CodeQL workflow property below.
val codeqlAnalysisBuild = providers.gradleProperty("dicodePing.codeql")
    .map { it.equals("true", ignoreCase = true) }
    .orElse(false)

val releaseKeystorePath = providers.environmentVariable("ANDROID_KEYSTORE_PATH").orNull
val releaseKeystorePassword = providers.environmentVariable("ANDROID_KEYSTORE_PASSWORD").orNull
val releaseKeyAlias = providers.environmentVariable("ANDROID_KEY_ALIAS").orNull
val releaseKeyPassword = providers.environmentVariable("ANDROID_KEY_PASSWORD").orNull
val releaseSigningReady = listOf(
    releaseKeystorePath,
    releaseKeystorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
).all { !it.isNullOrBlank() }

val verifyCore by tasks.registering {
    group = "build setup"
    description = "Validates the pinned Android connection core."

    doLast {
        if (codeqlAnalysisBuild.get()) {
            logger.lifecycle("CodeQL compilation: packaged native runtime verification is intentionally skipped.")
            return@doLast
        }
        if (!coreAar.isFile) {
            throw GradleException(
                "Missing Android runtime. Run PREPARE_V3_RUNTIME.bat from the repository root " +
                    "or execute tools/fetch_runtime_assets.py --android before building."
            )
        }
        if (coreAar.length() < 1_000_000L) {
            throw GradleException("Android core is too small or incomplete: ${coreAar.absolutePath}")
        }

        val digest = MessageDigest.getInstance("SHA-256")
        coreAar.inputStream().buffered().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        val actualSha256 = digest.digest().joinToString("") { "%02x".format(it) }
        if (!actualSha256.equals(coreSha256, ignoreCase = true)) {
            throw GradleException(
                "Android core SHA-256 mismatch. Expected $coreSha256, got $actualSha256"
            )
        }

        val entries = runCatching {
            ZipFile(coreAar).use { zip -> zip.entries().asSequence().map { it.name }.toSet() }
        }.getOrElse { cause ->
            throw GradleException("Android core is not a readable AAR/ZIP: ${coreAar.absolutePath}", cause)
        }

        if ("classes.jar" !in entries) {
            throw GradleException("Android core is invalid: classes.jar is missing.")
        }
        if (entries.none { it.matches(Regex("""jni/.+/(libgojni|libv2ray)\.so""")) }) {
            throw GradleException("Android core is invalid: native Android libraries are missing.")
        }
        for (abi in listOf("arm64-v8a", "armeabi-v7a", "x86_64")) {
            if (entries.none { it.startsWith("jni/$abi/") && it.endsWith(".so") }) {
                throw GradleException("Android core is missing required ABI: $abi")
            }
        }


        logger.lifecycle("Using Android core: ${coreAar.absolutePath}")
    }
}

android {
    namespace = "ir.dicode.ping"
    compileSdk = 36

    defaultConfig {
        applicationId = "ir.dicode.ping.client"
        minSdk = 24
        targetSdk = 36
        versionCode = 72
        versionName = "3.0.0-pre.3"
        buildConfigField("String", "RELEASE_VERSION", "\"3.0.0-pre.3\"")
        multiDexEnabled = true

    }

    flavorDimensions += "distribution"
    productFlavors {
        create("standard") {
            dimension = "distribution"
            buildConfigField("Boolean", "ENABLE_ROOT_TETHERING", "false")
            ndk { abiFilters += setOf("arm64-v8a", "armeabi-v7a", "x86_64") }
        }
        create("rooted") {
            dimension = "distribution"
            applicationIdSuffix = ".rooted"
            versionNameSuffix = "-rooted"
            buildConfigField("Boolean", "ENABLE_ROOT_TETHERING", "true")
            ndk { abiFilters += setOf("arm64-v8a", "armeabi-v7a", "x86_64") }
        }
    }

    signingConfigs {
        if (releaseSigningReady) {
            create("release") {
                storeFile = file(releaseKeystorePath!!)
                storePassword = releaseKeystorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                enableV4Signing = false
            }
        }
    }

    buildTypes {
        debug {
            // Local debug builds keep the standard Android debug key.
        }
        release {
            isDebuggable = false
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    splits {
        abi {
            isEnable = false
        }
    }

    bundle {
        language {
            enableSplit = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }
    lint {
        abortOnError = true
        checkReleaseBuilds = true
        // Release builds fail on real lint errors while preserving warnings as diagnostics.
        warningsAsErrors = false
        ignoreWarnings = false
        checkAllWarnings = false
        checkDependencies = true
        lintConfig = file("lint.xml")
        htmlReport = true
        textReport = true
        sarifReport = true
    }

    packaging {
        jniLibs.keepDebugSymbols += setOf("**/libgojni.so", "**/libv2ray.so")
        resources.excludes += setOf("META-INF/DEPENDENCIES", "META-INF/LICENSE*", "META-INF/NOTICE*")
    }
}

tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(verifyCore)
}

tasks.matching { task ->
    task.name.contains("Release", ignoreCase = true) &&
        (task.name.startsWith("assemble") || task.name.startsWith("bundle") || task.name.startsWith("validateSigning"))
}.configureEach {
    doFirst {
        if (!releaseSigningReady) {
            throw GradleException(
                "Release signing is not configured. Set ANDROID_KEYSTORE_PATH, " +
                    "ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS and ANDROID_KEY_PASSWORD."
            )
        }
    }
}

dependencies {
    implementation("ir.dicode.local:libv2ray:$coreVersion@aar") {
        isTransitive = false
    }

    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.10.0")
    implementation("androidx.fragment:fragment-ktx:1.8.5")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.constraintlayout:constraintlayout:2.2.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.multidex:multidex:2.0.1")

    testImplementation("junit:junit:4.13.2")
}
