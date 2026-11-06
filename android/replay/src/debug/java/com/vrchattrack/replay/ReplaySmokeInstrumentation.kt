package com.vrchattrack.replay

import android.app.Activity
import android.app.Instrumentation
import android.os.Bundle
import java.io.File

/** Debug-only headless test, invoked explicitly by adb; never starts the camera UI. */
class ReplaySmokeInstrumentation : Instrumentation() {
    private var mode = ReplayMode.IMAGE
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        mode = ReplayMode.valueOf(arguments?.getString("mode") ?: "IMAGE")
        start()
    }
    override fun onStart() {
        val result = Bundle()
        try {
            val context = targetContext
            val sourceFile = File(context.cacheDir, "smoke-source.zip")
            require(sourceFile.length() in 1..ReplayArchive.MAX_ZIP_BYTES.toLong())
            val source = ReplayArchive.read(sourceFile.readBytes())
            val gate = ReplayGate()
            val ticket = gate.begin()
            val report = try {
                ReplayRunner.run(source, ReplayPlan(mode, ReplayDelegate.CPU), gate, ticket,
                    factory = { model, settings -> AndroidReplayInference(context, model, settings) })
            } finally { gate.finish(ticket) }
            report.put("runtime", androidReplayRuntime(context).put("testHarness", "debug-instrumentation"))
            val output = File(context.noBackupFilesDir, "smoke-${mode.name.lowercase()}.json")
            check(!output.exists()) { "Test report already exists" }
            output.writeText(report.toString())
            val cases = report.getJSONArray("cases")
            require((0 until cases.length()).all { cases.getJSONObject(it).getString("status") == "completed" }) {
                "One or more native inference cases failed; inspect private report"
            }
            result.putString("stream", "NATIVE_REPLAY_COMPLETE mode=$mode frames=${source.frames.size} cases=2 no network/camera permissions; report=${output.name}\n")
            finish(Activity.RESULT_OK, result)
        } catch (problem: Throwable) {
            result.putString("stream", "NATIVE_REPLAY_FAILED ${problem.javaClass.simpleName}: ${problem.message}\n")
            finish(Activity.RESULT_CANCELED, result)
        }
    }
}
