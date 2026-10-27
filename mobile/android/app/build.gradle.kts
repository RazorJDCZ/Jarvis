import java.util.Properties

plugins {
    id("com.android.application")
}

val rootEnv = rootProject.projectDir.resolve("../../.env")
val defaultUrl = if (rootEnv.isFile) {
    rootEnv.readLines()
        .firstOrNull { it.trimStart().startsWith("JARVIS_REMOTE_ORIGIN=") }
        ?.substringAfter('=')
        ?.trim()
        ?.trim('"', '\'')
        .orEmpty()
} else ""

android {
    namespace = "com.juandi.jarvis"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.juandi.jarvis"
        minSdk = 29
        targetSdk = 36
        versionCode = 6
        versionName = "1.3.1"
        buildConfigField("String", "DEFAULT_JARVIS_URL", "\"${defaultUrl.replace("\\", "\\\\").replace("\"", "\\\"")}\"")
        resValue(
            "string",
            "asset_statements",
            "[{\\\"include\\\":\\\"$defaultUrl/.well-known/assetlinks.json\\\"}]",
        )
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.credentials:credentials:1.6.0-beta02")
    implementation("androidx.credentials:credentials-play-services-auth:1.6.0-beta02")
    implementation("androidx.webkit:webkit:1.14.0")
}
