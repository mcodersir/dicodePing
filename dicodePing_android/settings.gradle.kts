pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // Manually installed libv2ray AAR. Keeping it in a local Maven repository gives
        // AGP a real module identity and a stable extracted AAR directory.
        maven {
            name = "dicodeLocalCore"
            url = uri(rootDir.resolve("local-maven"))
            content { includeGroup("ir.dicode.local") }
            metadataSources {
                mavenPom()
                artifact()
            }
        }
        google()
        mavenCentral()
    }
}

rootProject.name = "dicodePing-Android"
include(":app")
