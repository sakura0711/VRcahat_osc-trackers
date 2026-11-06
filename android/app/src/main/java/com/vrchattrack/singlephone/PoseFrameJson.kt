package com.vrchattrack.singlephone

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.round

/** Shared serialization for the local image pair and the optional LAN sender. */
fun poseFrameJson(frame: PoseFrame): JSONObject {
    val points = JSONArray()
    val world = JSONArray()
    if (frame.poseDetected) {
        require(frame.landmarks.size == 33 && frame.worldLandmarks.size == 33)
        frame.landmarks.forEach { points.put(landmarkJson(it.x, it.y, it.z, it.visibility, it.presence)) }
        frame.worldLandmarks.forEach { world.put(landmarkJson(it.x, it.y, it.z, it.visibility, it.presence)) }
    }
    return JSONObject()
        .put("version", 1)
        .put("resultTimestampMs", frame.captureTimestampMs)
        .put("captureMonotonicNs", frame.cameraTimestampNs ?: 0L)
        .put("captureTimestampSource", "camera-device-unspecified")
        .put("analysisStartMonotonicNs", frame.analysisStartMonotonicNs ?: 0L)
        .put("inferenceMs", frame.timing?.totalMs ?: frame.inferenceMs.toDouble())
        .put("personDetected", frame.poseDetected)
        .put("imageWidth", frame.imageWidth)
        .put("imageHeight", frame.imageHeight)
        .put("inputRotationDegrees", frame.inputRotationDegrees ?: JSONObject.NULL)
        .put("mirroredInput", frame.mirroredInput ?: JSONObject.NULL)
        .put("modelAsset", frame.modelAsset)
        .put("landmarks", points)
        .put("worldLandmarks", world)
}

private fun landmarkJson(x: Float, y: Float, z: Float, visibility: Float?, presence: Float?): JSONObject {
    fun rounded(v: Float): Double {
        require(v.isFinite()) { "姿勢資料包含無效數值" }
        return round(v.toDouble() * 10_000.0) / 10_000.0
    }
    return JSONObject().put("x", rounded(x)).put("y", rounded(y)).put("z", rounded(z))
        .put("visibility", visibility?.let(::rounded) ?: JSONObject.NULL)
        .put("presence", presence?.let(::rounded) ?: JSONObject.NULL)
}
