package com.vrchattrack.singlephone

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.os.SystemClock
import android.util.Log
import androidx.camera.core.ImageProxy
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.framework.image.MPImage
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.core.Delegate
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.poselandmarker.PoseLandmarker
import com.google.mediapipe.tasks.vision.poselandmarker.PoseLandmarkerResult
import java.io.Closeable
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.roundToLong

data class LandmarkSample(
    val x: Float,
    val y: Float,
    val z: Float,
    val visibility: Float?,
    val presence: Float?,
) {
    /**
     * A point is only as trustworthy as its weakest available confidence signal.
     * Some task versions may omit one or both signals, in which case null is shown
     * in the overlay rather than pretending that the point is high-confidence.
     */
    val confidence: Float?
        get() = listOfNotNull(visibility, presence).minOrNull()
}

data class WorldLandmarkSample(
    val x: Float,
    val y: Float,
    val z: Float,
    val visibility: Float?,
    val presence: Float?,
)

/** MediaPipe landmark indices used by the later joint-angle and OSC stages. */
object PoseKeypoints {
    const val LEFT_SHOULDER = 11
    const val RIGHT_SHOULDER = 12
    const val LEFT_ELBOW = 13
    const val RIGHT_ELBOW = 14
    const val LEFT_WRIST = 15
    const val RIGHT_WRIST = 16
    const val LEFT_HIP = 23
    const val RIGHT_HIP = 24
    const val LEFT_KNEE = 25
    const val RIGHT_KNEE = 26
    const val LEFT_ANKLE = 27
    const val RIGHT_ANKLE = 28

    val TRACKED = intArrayOf(
        LEFT_SHOULDER,
        RIGHT_SHOULDER,
        LEFT_ELBOW,
        RIGHT_ELBOW,
        LEFT_WRIST,
        RIGHT_WRIST,
        LEFT_HIP,
        RIGHT_HIP,
        LEFT_KNEE,
        RIGHT_KNEE,
        LEFT_ANKLE,
        RIGHT_ANKLE,
    )
}

/** Per-frame wall-clock durations; MediaPipe time includes its queue and callback scheduling. */
data class ProcessingTiming(
    val prepareMs: Double,
    val taskMs: Double,
    val extractMs: Double,
    val totalMs: Double,
)

data class PoseFrame(
    val captureTimestampMs: Long,
    // The camera timestamp's timebase is device-dependent; do not subtract it
    // from elapsedRealtimeNanos without checking the camera timestamp source.
    val cameraTimestampNs: Long?,
    val analysisStartMonotonicNs: Long?,
    val inferenceMs: Long,
    val delegate: Delegate,
    val timing: ProcessingTiming?,
    val imageWidth: Int,
    val imageHeight: Int,
    val landmarks: List<LandmarkSample>,
    val worldLandmarks: List<WorldLandmarkSample>,
    val coreJointsUsable: Boolean,
    val inputRotationDegrees: Int? = null,
    val mirroredInput: Boolean? = null,
    val modelAsset: String = "pose_landmarker_lite.task",
) {
    val poseDetected: Boolean
        get() = landmarks.size == LANDMARK_COUNT

    val keyLandmarksWithConfidence: Int
        get() = PoseKeypoints.TRACKED.count { index ->
            landmarks.getOrNull(index)?.confidence != null
        }

    val keyLandmarksAboveThreshold: Int
        get() = PoseKeypoints.TRACKED.count { index ->
            val confidence = landmarks.getOrNull(index)?.confidence
            confidence != null && confidence >= CONFIDENCE_THRESHOLD
        }

    companion object {
        const val LANDMARK_COUNT = 33
        const val CONFIDENCE_THRESHOLD = 0.50f
    }
}

/**
 * Owns a CPU or GPU Pose Landmarker in LIVE_STREAM mode.
 *
 * This class is used from one CameraX analysis executor. ImageProxy ownership is
 * transferred to analyze(), which always closes it before returning.
 */
class PoseLandmarkerEngine(
    context: Context,
    private val listener: Listener,
    val delegate: Delegate,
) : Closeable {
    private data class PendingTiming(val startNs: Long, val submitNs: Long, val cameraTimestampNs: Long,
                                     val rotationDegrees: Int, val mirrored: Boolean)

    private val isClosed = AtomicBoolean(false)
    private val poseLandmarker: PoseLandmarker
    private val pendingTimings = ConcurrentHashMap<Long, PendingTiming>()
    private val poseRateMeter = PoseRateMeter()
    private var lastDebugLogAtMs = 0L
    // These are only used by the single CameraX analysis executor.
    private var lastTimestampMs = 0L
    private var lastCleanupNs = 0L

    init {
        val baseOptions =
            BaseOptions.builder()
                .setDelegate(delegate)
                .setModelAssetPath(MODEL_NAME)
                .build()

        val options =
            PoseLandmarker.PoseLandmarkerOptions.builder()
                .setBaseOptions(baseOptions)
                .setRunningMode(RunningMode.LIVE_STREAM)
                .setNumPoses(1)
                .setMinPoseDetectionConfidence(MIN_CONFIDENCE)
                .setMinPosePresenceConfidence(MIN_CONFIDENCE)
                .setMinTrackingConfidence(MIN_CONFIDENCE)
                .setResultListener(::onLiveStreamResult)
                .setErrorListener(::onLiveStreamError)
                .build()

        poseLandmarker = PoseLandmarker.createFromOptions(context, options)
    }

    fun analyze(imageProxy: ImageProxy, isFrontCamera: Boolean) {
        val startNs = SystemClock.elapsedRealtimeNanos()
        if (isClosed.get()) {
            imageProxy.close()
            return
        }

        var imageProxyClosed = false
        var submittedTimestampMs: Long? = null
        try {
            // MediaPipe requires increasing timestamps, including on fast devices.
            val captureTimestampMs = maxOf(SystemClock.uptimeMillis(), lastTimestampMs + 1L)
            lastTimestampMs = captureTimestampMs
            val width = imageProxy.width
            val height = imageProxy.height
            val rotationDegrees = imageProxy.imageInfo.rotationDegrees
            val cameraTimestampNs = imageProxy.imageInfo.timestamp
            val bitmapBuffer = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            imageProxy.planes[0].buffer.rewind()
            bitmapBuffer.copyPixelsFromBuffer(imageProxy.planes[0].buffer)
            imageProxy.close()
            imageProxyClosed = true

            val transform =
                Matrix().apply {
                    postRotate(rotationDegrees.toFloat())
                    if (isFrontCamera) {
                        postScale(-1f, 1f, width.toFloat(), height.toFloat())
                    }
                }
            val rotatedBitmap =
                Bitmap.createBitmap(
                    bitmapBuffer,
                    0,
                    0,
                    bitmapBuffer.width,
                    bitmapBuffer.height,
                    transform,
                    true,
                )
            val image = BitmapImageBuilder(rotatedBitmap).build()
            val submitNs = SystemClock.elapsedRealtimeNanos()
            pendingTimings[captureTimestampMs] = PendingTiming(startNs, submitNs, cameraTimestampNs,
                                                             rotationDegrees, isFrontCamera)
            submittedTimestampMs = captureTimestampMs
            poseLandmarker.detectAsync(image, captureTimestampMs)

            // LIVE_STREAM may drop frames and never call back for them. Bound the
            // bookkeeping without expiring a normal in-flight inference.
            if (startNs - lastCleanupNs >= CLEANUP_INTERVAL_NS) {
                lastCleanupNs = startNs
                val cutoffNs = startNs - MAX_PENDING_AGE_NS
                pendingTimings.forEach { (timestamp, timing) ->
                    if (timing.startNs < cutoffNs) {
                        pendingTimings.remove(timestamp, timing)
                    }
                }
            }
        } catch (error: Exception) {
            submittedTimestampMs?.let { pendingTimings.remove(it) }
            Log.e(TAG, "Unable to submit a camera frame to Pose Landmarker", error)
            listener.onError(error.message ?: error.javaClass.simpleName)
        } finally {
            if (!imageProxyClosed) {
                imageProxy.close()
            }
        }
    }

    override fun close() {
        if (isClosed.compareAndSet(false, true)) {
            poseLandmarker.close()
            pendingTimings.clear()
        }
    }

    private fun onLiveStreamResult(result: PoseLandmarkerResult, input: com.google.mediapipe.framework.image.MPImage) {
        if (isClosed.get()) return
        val callbackNs = SystemClock.elapsedRealtimeNanos()
        val pending = pendingTimings.remove(result.timestampMs())
        val normalized =
            result.landmarks().firstOrNull().orEmpty().map { landmark ->
                LandmarkSample(
                    x = landmark.x(),
                    y = landmark.y(),
                    z = landmark.z(),
                    visibility = landmark.visibility().orElse(null),
                    presence = landmark.presence().orElse(null),
                )
            }
        val world =
            result.worldLandmarks().firstOrNull().orEmpty().map { landmark ->
                WorldLandmarkSample(
                    x = landmark.x(),
                    y = landmark.y(),
                    z = landmark.z(),
                    visibility = landmark.visibility().orElse(null),
                    presence = landmark.presence().orElse(null),
                )
            }
        val coreUsable = coreJointsAreUsable(normalized)
        val extractionEndNs = SystemClock.elapsedRealtimeNanos()
        val timing = pending?.let {
            ProcessingTiming(
                prepareMs = (it.submitNs - it.startNs) / NANOS_PER_MS,
                taskMs = (callbackNs - it.submitNs) / NANOS_PER_MS,
                extractMs = (extractionEndNs - callbackNs) / NANOS_PER_MS,
                totalMs = (extractionEndNs - it.startNs) / NANOS_PER_MS,
            )
        }
        val frame =
            PoseFrame(
                captureTimestampMs = result.timestampMs(),
                cameraTimestampNs = pending?.cameraTimestampNs,
                analysisStartMonotonicNs = pending?.startNs,
                inferenceMs = timing?.totalMs?.roundToLong()
                    ?: (SystemClock.uptimeMillis() - result.timestampMs()).coerceAtLeast(0L),
                delegate = delegate,
                timing = timing,
                imageWidth = input.width,
                imageHeight = input.height,
                landmarks = normalized,
                worldLandmarks = world,
                coreJointsUsable = coreUsable,
                inputRotationDegrees = pending?.rotationDegrees,
                mirroredInput = pending?.mirrored,
                modelAsset = MODEL_NAME,
            )
        poseRateMeter.record(SystemClock.elapsedRealtimeNanos(), frame.poseDetected)?.let { window ->
            val durationMs = window.durationNs / NANOS_PER_MS
            Log.i(
                TAG,
                String.format(
                    Locale.US,
                    "POSE_RATE delegate=%s durationMs=%.2f results=%d poses=%d resultFps=%.2f poseFps=%.2f",
                    delegate, durationMs, window.results, window.poses,
                    window.results * 1_000.0 / durationMs, window.poses * 1_000.0 / durationMs,
                ),
            )
        }
        emitDebugLog(frame)
        listener.onPoseFrame(frame)
        listener.onDiagnosticFrame(frame, input)
    }

    private fun onLiveStreamError(error: RuntimeException) {
        Log.e(TAG, "Pose Landmarker runtime error", error)
        listener.onError(error.message ?: error.javaClass.simpleName)
    }

    private fun coreJointsAreUsable(landmarks: List<LandmarkSample>): Boolean {
        if (landmarks.size != PoseFrame.LANDMARK_COUNT) {
            return false
        }
        return PoseKeypoints.TRACKED.all { index ->
            val landmark = landmarks[index]
            val confidence = landmark.confidence
            confidence == null || confidence >= MIN_CONFIDENCE
        }
    }

    private fun emitDebugLog(frame: PoseFrame) {
        val now = SystemClock.uptimeMillis()
        if (now - lastDebugLogAtMs < DEBUG_LOG_INTERVAL_MS) {
            return
        }
        lastDebugLogAtMs = now
        val timing = frame.timing
        if (timing != null) {
            Log.i(
                TAG,
                String.format(
                    Locale.US,
                    "TIMING delegate=%s pose=%b prepMs=%.2f taskMs=%.2f extractMs=%.2f totalMs=%.2f keyConfidence=%d/%d",
                    delegate, frame.poseDetected, timing.prepareMs, timing.taskMs,
                    timing.extractMs, timing.totalMs,
                    frame.keyLandmarksAboveThreshold, frame.keyLandmarksWithConfidence,
                ),
            )
        } else {
            Log.w(TAG, "TIMING delegate=$delegate pose=${frame.poseDetected} timing=unavailable")
        }
    }

    interface Listener {
        fun onPoseFrame(frame: PoseFrame)

        fun onDiagnosticFrame(frame: PoseFrame, input: MPImage) {}

        fun onError(message: String)
    }

    companion object {
        private const val TAG = "PoseLandmarkerEngine"
        private const val MODEL_NAME = "pose_landmarker_lite.task"
        private const val MIN_CONFIDENCE = 0.50f
        private const val DEBUG_LOG_INTERVAL_MS = 1_000L
        private const val NANOS_PER_MS = 1_000_000.0
        private const val CLEANUP_INTERVAL_NS = 1_000_000_000L
        private const val MAX_PENDING_AGE_NS = 10_000_000_000L
    }
}

