package com.vrchattrack.singlephone

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import java.util.Locale
import kotlin.math.max

/**
 * Debug-only overlay for the main body joints used during pose inspection.
 * It intentionally omits face, fingers, and foot tips to keep the display readable.
 */
class PoseOverlayView(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {
    private var frame: PoseFrame? = null
    private val density = resources.displayMetrics.density

    private val pointPaint =
        Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
        }
    private val textPaint =
        Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = 12f * density
            style = Paint.Style.FILL
            setShadowLayer(3f * density, 1f, 1f, Color.BLACK)
        }
    private val bannerPaint =
        Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.argb(180, 0, 0, 0)
            style = Paint.Style.FILL
        }

    fun setPoseFrame(frame: PoseFrame) {
        this.frame = frame
        invalidate()
    }

    fun clear() {
        frame = null
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val current = frame ?: return
        if (!current.poseDetected || current.imageWidth <= 0 || current.imageHeight <= 0) {
            drawBanner(canvas, "NO POSE")
            return
        }

        val transform = buildTransform(current)
        drawKeypoints(canvas, current, transform)

        val confidenceText =
            if (current.keyLandmarksWithConfidence == 0) {
                "confidence: unavailable"
            } else {
                "confidence: " + current.keyLandmarksAboveThreshold +
                    "/" + current.keyLandmarksWithConfidence + " >= 0.50"
            }
        drawBanner(
            canvas,
            "POSE 33/33 | " + confidenceText + " | total " + current.inferenceMs + " ms",
        )
    }

    private fun buildTransform(frame: PoseFrame): DisplayTransform {
        val scale = max(width.toFloat() / frame.imageWidth, height.toFloat() / frame.imageHeight)
        val renderedWidth = frame.imageWidth * scale
        val renderedHeight = frame.imageHeight * scale
        return DisplayTransform(
            scale = scale,
            offsetX = (width - renderedWidth) / 2f,
            offsetY = (height - renderedHeight) / 2f,
        )
    }

    private fun drawKeypoints(
        canvas: Canvas,
        frame: PoseFrame,
        transform: DisplayTransform,
    ) {
        KEYPOINTS.forEach { keypoint ->
            val landmark = frame.landmarks.getOrNull(keypoint.index) ?: return@forEach
            val point = displayPoint(landmark, frame, transform)
            pointPaint.color = colorForConfidence(landmark.confidence)
            canvas.drawCircle(point.first, point.second, 7f * density, pointPaint)
            canvas.drawText(
                keypoint.label + " " + confidenceLabel(landmark.confidence),
                point.first + 9f * density,
                max(16f * density, point.second - 8f * density),
                textPaint,
            )
        }
    }

    private fun displayPoint(
        landmark: LandmarkSample,
        frame: PoseFrame,
        transform: DisplayTransform,
    ): Pair<Float, Float> =
        Pair(
            transform.offsetX + landmark.x * frame.imageWidth * transform.scale,
            transform.offsetY + landmark.y * frame.imageHeight * transform.scale,
        )

    private fun drawBanner(canvas: Canvas, text: String) {
        val padding = 10f * density
        val top = 12f * density
        val height = 30f * density
        canvas.drawRoundRect(
            RectF(padding, top, width - padding, top + height),
            6f * density,
            6f * density,
            bannerPaint,
        )
        canvas.drawText(text, 18f * density, top + 20f * density, textPaint)
    }

    private fun confidenceLabel(confidence: Float?): String =
        confidence?.let { String.format(Locale.US, "%.2f", it) } ?: "?"

    private fun colorForConfidence(vararg confidences: Float?): Int {
        val available = confidences.filterNotNull()
        if (available.isEmpty()) {
            return COLOR_UNKNOWN
        }
        return when {
            available.min() >= HIGH_CONFIDENCE -> COLOR_HIGH
            available.min() >= PoseFrame.CONFIDENCE_THRESHOLD -> COLOR_MEDIUM
            else -> COLOR_LOW
        }
    }

    private data class DisplayTransform(
        val scale: Float,
        val offsetX: Float,
        val offsetY: Float,
    )

    private data class Keypoint(
        val index: Int,
        val label: String,
    )

    private companion object {
        const val HIGH_CONFIDENCE = 0.75f
        const val COLOR_HIGH = 0xFF31D87B.toInt()
        const val COLOR_MEDIUM = 0xFFFFD54F.toInt()
        const val COLOR_LOW = 0xFFFF5252.toInt()
        const val COLOR_UNKNOWN = 0xFFB0BEC5.toInt()

        val KEYPOINTS =
            listOf(
                Keypoint(PoseKeypoints.LEFT_SHOULDER, "LSh"),
                Keypoint(PoseKeypoints.RIGHT_SHOULDER, "RSh"),
                Keypoint(PoseKeypoints.LEFT_ELBOW, "LEl"),
                Keypoint(PoseKeypoints.RIGHT_ELBOW, "REl"),
                Keypoint(PoseKeypoints.LEFT_WRIST, "LWr"),
                Keypoint(PoseKeypoints.RIGHT_WRIST, "RWr"),
                Keypoint(PoseKeypoints.LEFT_HIP, "LHp"),
                Keypoint(PoseKeypoints.RIGHT_HIP, "RHp"),
                Keypoint(PoseKeypoints.LEFT_KNEE, "LKn"),
                Keypoint(PoseKeypoints.RIGHT_KNEE, "RKn"),
                Keypoint(PoseKeypoints.LEFT_ANKLE, "LAn"),
                Keypoint(PoseKeypoints.RIGHT_ANKLE, "RAn"),
            )
    }
}

