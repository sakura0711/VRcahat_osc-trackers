package com.vrchattrack.replay

import org.json.JSONArray
import org.json.JSONObject
import java.io.Closeable
import java.util.UUID

class ReplayCancelled : RuntimeException("Replay cancelled")

/** Cancellation does not release worker ownership until GPU resources are closed. */
class ReplayGate {
    data class Ticket(val generation: Long)
    private var generation = 0L
    private var active: Ticket? = null
    private var stopped = false
    @Synchronized fun begin(): Ticket {
        check(active == null) { "Worker still owns resources" }
        return Ticket(++generation).also { active = it; stopped = false }
    }
    @Synchronized fun cancel() { stopped = true }
    @Synchronized fun current(ticket: Ticket) = active == ticket && !stopped
    @Synchronized fun busy() = active != null
    @Synchronized fun finish(ticket: Ticket) { if (active == ticket) active = null }
    @Synchronized fun publish(ticket: Ticket, action: () -> Unit): Boolean {
        if (!current(ticket)) return false
        action()
        return true
    }
}

enum class ReplayModel(val asset: String, val sha256: String) {
    LITE("pose_landmarker_lite.task", "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"),
    FULL("pose_landmarker_full.task", "4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad"),
}
enum class ReplayMode { IMAGE, VIDEO }
enum class ReplayDelegate { CPU, GPU }
data class ReplayPlan(val mode: ReplayMode = ReplayMode.IMAGE, val delegate: ReplayDelegate = ReplayDelegate.CPU)

data class ReplaySample(val detected: Boolean, val normalized: JSONArray, val world: JSONArray,
                        val taskTimestampMs: Long, val elapsedMs: Double) {
    fun result(frame: ReplayFrame, mode: ReplayMode): JSONObject {
        validatePoints(normalized, if (detected) 33 else 0)
        validatePoints(world, if (detected) 33 else 0)
        require(elapsedMs.isFinite() && elapsedMs >= 0) { "Invalid inference elapsed time" }
        if (mode == ReplayMode.VIDEO) require(taskTimestampMs >= 0 && taskTimestampMs == frame.sourceFrameId) { "Video result timestamp mismatch" }
        return frame.identity().put("personDetected", detected)
            .put("inputTimestampMs", if (mode == ReplayMode.VIDEO) frame.sourceFrameId else JSONObject.NULL)
            .put("taskResultTimestampMs", if (mode == ReplayMode.VIDEO) taskTimestampMs else JSONObject.NULL)
            .put("frameworkTimestampMs", taskTimestampMs).put("inferenceElapsedMs", elapsedMs)
            .put("landmarks", normalized).put("worldLandmarks", world)
    }
}

interface ReplayInference : Closeable { fun infer(frame: ReplayFrame): ReplaySample }

object ReplayRunner {
    const val TASKS_VERSION = "1.0.0"
    fun run(source: ReplaySource, plan: ReplayPlan, gate: ReplayGate, ticket: ReplayGate.Ticket,
            factory: (ReplayModel, ReplayPlan) -> ReplayInference,
            progress: (ReplayModel, Int, Int) -> Unit = { _, _, _ -> }): JSONObject {
        fun checkActive() { if (!gate.current(ticket)) throw ReplayCancelled() }
        val cases = JSONArray()
        for (model in ReplayModel.entries) {
            checkActive()
            val case = JSONObject().put("model", model.name.lowercase()).put("modelAsset", model.asset)
                .put("modelSha256", model.sha256).put("requestedDelegate", plan.delegate.name)
                .put("runningMode", plan.mode.name).put("fallbackUsed", false)
            val results = JSONArray()
            try {
                factory(model, plan).use { engine ->
                    for (frame in source.frames) {
                        checkActive()
                        val sample = engine.infer(frame)
                        checkActive()
                        results.put(sample.result(frame, plan.mode))
                        progress(model, frame.index, source.frames.size)
                    }
                }
                checkActive()
                case.put("status", "completed").put("configuredDelegate", plan.delegate.name).put("results", results)
            } catch (cancelled: ReplayCancelled) { throw cancelled
            } catch (problem: Exception) {
                checkActive()
                case.put("status", "error").put("errorKind", problem.javaClass.simpleName)
                    .put("errorMessage", (problem.message ?: "").take(512)).put("results", JSONArray())
            } catch (problem: LinkageError) {
                checkActive()
                case.put("status", "error").put("errorKind", problem.javaClass.simpleName)
                    .put("errorMessage", (problem.message ?: "").take(512)).put("results", JSONArray())
            }
            cases.put(case)
        }
        checkActive()
        return JSONObject().put("format", "vrchat-track-android-replay").put("version", 1)
            .put("runId", UUID.randomUUID().toString()).put("tasksVisionVersion", TASKS_VERSION)
            .put("oscOutputEnabled", false).put("originalLiveStreamReconstructed", false)
            .put("source", JSONObject().put("zipSha256", source.zipSha256).put("captureSession", source.captureSession)
                .put("appVersion", source.appVersion).put("frameCount", source.frames.size))
            .put("sourceFrames", JSONArray().also { a -> source.frames.forEach { a.put(it.identity()) } })
            .put("cases", cases)
    }
}
