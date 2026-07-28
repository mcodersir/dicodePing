buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath("com.android.tools.build:gradle:9.3.1")
    }
}

plugins {
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
