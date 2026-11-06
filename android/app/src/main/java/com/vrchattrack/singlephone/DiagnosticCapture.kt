package com.vrchattrack.singlephone

import android.content.Context
import android.graphics.Bitmap
import android.os.SystemClock
import com.google.mediapipe.framework.image.BitmapExtractor
import com.google.mediapipe.framework.image.MPImage
import org.json.JSONObject
import java.io.Closeable
import java.io.File
import java.io.OutputStream
import java.util.concurrent.Executors

/** Local, explicit diagnostic capture. It has no network sender. */
class DiagnosticCapture(context: Context) : Closeable {
    private val app = context.applicationContext
    private val gate = DiagnosticCaptureGate()
    private val store = DiagnosticPairStore(File(app.noBackupFilesDir, "diagnostic-pairs"))
    private val writer = Executors.newSingleThreadExecutor()
    @Volatile private var session: DiagnosticPairStore.Session? = null
    @Volatile private var lastCompleted = store.latest()
    @Volatile private var saved = 0
    @Volatile private var error: String? = null
    @Volatile private var closed = false

    @Synchronized fun start() {
        check(!closed)
        stop()
        saved = 0
        error = null
        @Suppress("DEPRECATION")
        val version = app.packageManager.getPackageInfo(app.packageName, 0).versionName
        session = store.start { id ->
            JSONObject().put("format", "vrchat-track-image-pairs").put("version", 1)
                .put("captureSession", id).put("appVersion", version)
                .put("durationSeconds", 120).put("intervalSeconds", 3).put("maximumFrames", 40)
                .put("createdUnixMs", System.currentTimeMillis()).put("oscOutputEnabled", false).toString()
        }
        gate.start(SystemClock.elapsedRealtimeNanos())
    }

    @Synchronized fun stop() = gate.stop()
    fun isActive(): Boolean = !closed && gate.isActive(SystemClock.elapsedRealtimeNanos())
    fun hasExport(): Boolean = lastCompleted != null
    fun status(): String = when {
        error != null -> "影像對照：${error}（已保存 $saved 張）"
        isActive() -> "影像對照：已保存 $saved 張；每 3 秒一張，最長 120 秒，僅存本機"
        else -> "影像對照：預設關閉／已停止（本輪 $saved 張）。手動開始才保存影像與座標，僅存本機。"
    }

    fun offer(frame: PoseFrame, input: MPImage) {
        val (current, ticket) = synchronized(this) {
            if (closed) return
            val current = session ?: return
            val ticket = gate.reserve(SystemClock.elapsedRealtimeNanos(), frame.captureTimestampMs) ?: return
            current to ticket
        }
        var owned: Bitmap? = null
        try {
            check(frame.inputRotationDegrees != null && frame.mirroredInput != null) { "缺少影格方向資訊" }
            check(input.width == frame.imageWidth && input.height == frame.imageHeight)
            check(input.width.toLong() * input.height <= 4_194_304) { "對照影像超過尺寸限制" }
            // The result callback owns input only during this call. Copy before returning.
            owned = requireNotNull(BitmapExtractor.extract(input).copy(Bitmap.Config.ARGB_8888, false))
            val bitmap = owned
            writer.execute {
                try {
                    store.writePair(current, ticket.index,
                        encode = { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) },
                        metadata = { sha ->
                            JSONObject().put("format", "vrchat-track-image-pair").put("version", 1)
                                .put("captureSession", current.id).put("frameId", frame.captureTimestampMs)
                                .put("image", JSONObject().put("file", "input.png").put("sha256", sha))
                                .put("packet", poseFrameJson(frame)).toString()
                        },
                        publish = { action -> gate.publish(ticket, SystemClock.elapsedRealtimeNanos()) {
                            action()
                            lastCompleted = current
                            saved++
                        } },
                    )
                } catch (problem: Exception) {
                    synchronized(this) {
                        if (session === current) {
                            error = "保存失敗：${problem.javaClass.simpleName}"
                            gate.stop()
                        }
                    }
                } finally {
                    bitmap.recycle()
                    gate.release(ticket)
                }
            }
            owned = null // Ownership transferred to the bounded worker.
        } catch (problem: Exception) {
            owned?.recycle()
            gate.release(ticket)
            synchronized(this) {
                if (session === current) {
                    error = "擷取失敗：${problem.javaClass.simpleName}"
                    gate.stop()
                }
            }
        }
    }

    fun export(output: OutputStream, completed: (String?) -> Unit) {
        stop()
        val source = lastCompleted
        if (source == null) {
            output.close()
            completed("沒有完整對照資料")
            return
        }
        writer.execute {
            try {
                store.export(source, output)
                completed(null)
            } catch (problem: Exception) {
                output.close()
                completed("匯出失敗：${problem.javaClass.simpleName}")
            }
        }
    }

    @Synchronized override fun close() {
        closed = true
        stop()
        writer.shutdown() // An owned bitmap must reach its finally/recycle block.
    }
}
