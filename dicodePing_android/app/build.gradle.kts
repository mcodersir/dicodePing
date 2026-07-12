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
val releaseKeyAlias = providers.environmentVariable("