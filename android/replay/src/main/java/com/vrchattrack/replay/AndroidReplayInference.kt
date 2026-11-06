package com.vrchattrack.replay

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.SystemClock
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.core.Delegate
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.poselandmarker.PoseLandmarker
import org.json.JSONArray
import org.json.JSONObject

/** Create, infer and close on one worker thread, including when GPU is selected. */
class AndroidReplayInference(context: Context, model: ReplayModel, private val plan: ReplayPlan) : ReplayInference {
    private val owner = Thread.currentThread()
    private val task: PoseLandmarker
    init {
        val hash = context.assets.open(model.asset).use { sha256(it.readBytes()) }
        check(hash == model.sha256) { "Packaged model hash mismatch" }
        val options = PoseLandmarker.PoseLandmarkerOptions.builder()
            .setBaseOptions(BaseOptions.builder().setModelAssetPath(model.asset)
                .setDelegate(if (plan.delegate == ReplayDelegate.GPU) Delegate.GPU else Delegate.CPU).build())
            .setRunningMode(if (plan.mode == ReplayMode.IMAGE) RunningMode.IMAGE else RunningMode.VIDEO)
            .setNumPoses(1).setMinPoseDetectionConfidence(0.5f)
            .setMinPosePresenceConfidence(0.5f).setMinTrackingConfidence(0.5f).build()
        // No automatic CPU fallback: a failure is recorded for the requested case.
        task = PoseLandmarker.createFromOptions(context, options)
    }

    override fun infer(frame: ReplayFrame): ReplaySample {
        check(Thread.currentThread() === owner)
        val options = BitmapFactory.Options().apply { inScaled = false; inPreferredConfig = Bitmap.Config.ARGB_8888 }
        val bitmap = requireNotNull(BitmapFactory.decodeByteArray(frame.png, 0, frame.png.size, options))
        try {
            require(bitmap.width == frame.width && bitmap.height == frame.height) { "Decoded image dimensions changed" }
            // The saved PNG is already rotated/mirrored. Do not apply either again.
            val image = BitmapImageBuilder(bitmap).build()
            try {
                val start = SystemClock.elapsedRealtimeNanos()
                val result = if (plan.mode == ReplayMode.IMAGE) task.detect(image)
                             else task.detectForVideo(image, frame.sourceFrameId)
                val elapsedMs = (SystemClock.elapsedRealtimeNanos() - start) / 1_000_000.0
                val normalized = JSONArray()
                val world = JSONArray()
                result.landmarks().firstOrNull()?.forEach { p ->
                    normalized.put(point(p.x(), p.y(), p.z(), p.visibility().orElse(null), p.presence().orElse(null)))
                }
                result.worldLandmarks().firstOrNull()?.forEach { p ->
                    world.put(point(p.x(), p.y(), p.z(), p.visibility().orElse(null), p.presence().orElse(null)))
                }
                return ReplaySample(result.landmarks().isNotEmpty(), normalized, world, result.timestampMs(), elapsedMs)
            } finally { image.close() }
        } finally { if (!bitmap.isRecycled) bitmap.recycle() }
    }

    override fun close() { check(Thread.currentThread() === owner); task.close() }

    private fun point(x: Float, y: Float, z: Float, visibility: Float?, presence: Float?) = JSONObject()
        .put("x", x.toDouble()).put("y", y.toDouble()).put("z", z.toDouble())
        .put("visibility", visibility?.toDouble() ?: JSONObject.NULL)
        .put("presence", presence?.toDouble() ?: JSONObject.NULL)
}
