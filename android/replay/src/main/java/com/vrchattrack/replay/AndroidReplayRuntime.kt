package com.vrchattrack.replay

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject

fun androidReplayRuntime(context: Context): JSONObject {
    val internet = context.packageManager.checkPermission(Manifest.permission.INTERNET, context.packageName) == PackageManager.PERMISSION_GRANTED
    val camera = context.packageManager.checkPermission(Manifest.permission.CAMERA, context.packageName) == PackageManager.PERMISSION_GRANTED
    check(!internet && !camera) { "Offline replay must not have network/camera permissions" }
    return JSONObject().put("applicationId", context.packageName).put("appVersion", "0.1.0")
        .put("androidSdk", Build.VERSION.SDK_INT).put("deviceModel", Build.MODEL)
        .put("supportedAbis", JSONArray(Build.SUPPORTED_ABIS.toList())).put("synthetic", false)
        .put("internetPermission", internet).put("cameraPermission", camera)
        .put("submissionPolicy", "synchronous-as-fast-as-possible")
}
