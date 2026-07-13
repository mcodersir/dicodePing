import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipFile

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val coreVersion = "26.6.2"
val coreSha256 = "367d6b2f74e62c974c61210c56802127812be4c9410a83a6b8b6cac765a7595e"
val coreAar = rootProject.file(
    "local-maven/ir/dicode/local/libv2ray/$coreVersion/libv2ray-$coreVersion.aar"
)

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
    description = "Validates the manually installed Android connection core."

    doLast {
        if (!coreAar.isFile) {
            throw GradleException(
                "Missing Android core. Download libv2ray.aar from " +
                    "https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.6.2/libv2ray.aar " +
                    "and save it as ${coreAar.absolutePath} before syncing/building."
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
        if (entries.none { it.matches(Regex("jni/.+/(libgojni|libv2ray)\\.so")) }) {
            throw GradleException("Android core is invalid: native Android libraries are missing.")
        }

        logger.lifecycle("Using Android core: ${coreAar.absolutePath}")
    }
}

android {
    namespace = "ir.dicode.ping"
    compileSdk = 35

    defaultConfig {
        applicationId = "ir.dicode.ping.client"
        minSdk = 24
        targetSdk = 35
        versionCode = 6
        versionName = "0.1.3"
        multiDexEnabled = true

        ndk {
            abiFilters += setOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")
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

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }

    packaging {
        jniLibs.useLegacyPackaging = true
        resources.excludes += setOf("META-INF/DEPENDENCIES", "META-INF/LICENSE*", "META-INF/NOTICE*")
    }
}

tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(verifyCore)
}

tasks.matching { it.name in setOf("preReleaseBuild", "validateSigningRelease", "assembleRelease") }.configureEach {
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
