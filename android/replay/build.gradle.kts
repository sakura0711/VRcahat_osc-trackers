import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.vrchattrack.replay"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.vrchattrack.replay"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

// Only pinned public models enter this APK. No photos, ZIPs or downloaded code.
val replayAssets = layout.buildDirectory.dir("generated/replayAssets")
val liteModel = rootProject.file("app/src/main/assets/pose_landmarker_lite.task")
val fullModel = providers.gradleProperty("poseFullModel").map { rootProject.file(it) }.getOrElse(
    rootProject.file("../windows/captures/pose-model-ab-20261106/models/pose_landmarker_full.task"),
)
val prepareReplayModels = tasks.register("prepareReplayModels") {
    inputs.files(liteModel, fullModel)
    outputs.dir(replayAssets)
    doLast {
        val models = listOf(
            liteModel to "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
            fullModel to "4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad",
        )
        val output = replayAssets.get().asFile.apply { mkdirs() }
        models.forEachIndexed { index, (source, expected) ->
            check(source.isFile) { "Provide the pinned local Full model using -PposeFullModel=PATH; no automatic download" }
            val sha = MessageDigest.getInstance("SHA-256").digest(source.readBytes())
                .joinToString("") { "%02x".format(it.toInt() and 255) }
            check(sha == expected) { "Replay model SHA-256 mismatch: ${source.name}" }
            source.copyTo(File(output, if (index == 0) "pose_landmarker_lite.task" else "pose_landmarker_full.task"), overwrite = true)
        }
    }
}
android.sourceSets.getByName("main").assets.srcDir(replayAssets)
tasks.named("preBuild").configure { dependsOn(prepareReplayModels) }

dependencies {
    implementation("com.google.mediapipe:tasks-vision:1.0.0")
    constraints {
        // Match the versions resolved in the camera app, without packaging its UI.
        implementation("androidx.annotation:annotation:1.8.1")
        implementation("com.google.guava:guava:33.3.1-android")
    }
}
