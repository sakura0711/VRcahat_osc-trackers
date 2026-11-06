package com.vrchattrack.replay

import org.json.JSONArray
import org.json.JSONObject
import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import javax.imageio.ImageIO

private fun rejected(action: () -> Unit) {
    var failed = false
    try { action() } catch (_: Exception) { failed = true }
    check(failed) { "Invalid input was accepted" }
}

fun main(args: Array<String>) {
    val png = ByteArrayOutputStream().also {
        check(ImageIO.write(BufferedImage(3, 2, BufferedImage.TYPE_INT_ARGB), "png", it))
    }.toByteArray()
    val points = JSONArray().also { a -> repeat(33) {
        a.put(JSONObject().put("x", 0.5).put("y", 0.5).put("z", 0.0)
            .put("visibility", 0.9).put("presence", 0.9))
    } }
    fun pair(id: Long) = JSONObject().put("format", "vrchat-track-image-pair").put("version", 1)
        .put("captureSession", "test").put("frameId", id)
        .put("image", JSONObject().put("file", "input.png").put("sha256", sha256(png)))
        .put("packet", JSONObject().put("version", 1).put("resultTimestampMs", id)
            .put("captureMonotonicNs", id + 1).put("analysisStartMonotonicNs", id + 2)
            .put("imageWidth", 3).put("imageHeight", 2).put("inputRotationDegrees", 270)
            .put("mirroredInput", true).put("modelAsset", "synthetic.task").put("personDetected", true)
            .put("landmarks", points).put("worldLandmarks", points))
    fun archive(pairs: List<JSONObject>, extra: String? = null): ByteArray = ByteArrayOutputStream().also { out ->
        ZipOutputStream(out).use { zip ->
            fun entry(name: String, value: ByteArray) {
                zip.putNextEntry(ZipEntry(name)); zip.write(value); zip.closeEntry()
            }
            entry("manifest.json", """{"format":"vrchat-track-image-pairs","version":1,"captureSession":"test","appVersion":"synthetic"}""".toByteArray())
            pairs.forEachIndexed { i, p ->
                val folder = "frame-${(i + 1).toString().padStart(4, '0')}"
                entry("$folder/input.png", png); entry("$folder/landmarks.json", p.toString().toByteArray())
            }
            if (extra != null) entry(extra, byteArrayOf(1))
        }
    }.toByteArray()

    val bytes = archive(listOf(pair(200), pair(100)))
    val source = ReplayArchive.read(bytes)
    check(source.zipSha256 == sha256(bytes))
    check(source.frames.map { it.sourceFrameId } == listOf(100L, 200L))
    check(source.frames.map { it.index } == listOf(1, 2))
    check(source.frames.all { it.png.contentEquals(png) && it.width == 3 && it.height == 2 && it.mirrored && it.rotation == 270 })
    rejected { ReplayArchive.read(archive(listOf(pair(100), pair(100)))) }
    rejected { ReplayArchive.read(archive(listOf(pair(100)), "../outside.txt")) }
    rejected { ReplayArchive.read(archive(listOf(pair(100)), "frame-0001/")) }
    rejected { ReplayArchive.read(archive(listOf(pair(100).apply { getJSONObject("image").put("sha256", "0".repeat(64)) }))) }
    rejected { ReplayArchive.read(archive(listOf(pair(100).apply { getJSONObject("packet").put("imageWidth", 2) }))) }
    rejected { ReplayArchive.read(archive(listOf(pair(100).apply { getJSONObject("packet").put("resultTimestampMs", 99) }))) }
    rejected { ReplayArchive.read(archive(listOf(pair(100).apply { getJSONObject("packet").put("mirroredInput", "true") }))) }
    rejected { ReplayArchive.read(archive(listOf(pair(100).apply { getJSONObject("packet").put("inputRotationDegrees", 4294967566L) }))) }
    rejected { ReplayArchive.read(archive(listOf(pair(100).apply { getJSONObject("packet").put("personDetected", false) }))) }
    rejected { ReplayArchive.pngDimensions(png.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }) }
    rejected { ReplayArchive.read(bytes) { true } }
    rejected { ReplayArchive.read(ByteArray(0)) }

    val gate = ReplayGate()
    val ticket = gate.begin()
    val inputBefore = source.frames.map { it.sourcePacket.toString() }
    val calls = mutableListOf<Pair<ReplayModel, ReplayPlan>>()
    var closed = 0
    fun fake(frame: ReplayFrame, mode: ReplayMode) = ReplaySample(
        frame.sourcePacket.getBoolean("personDetected"), frame.sourcePacket.getJSONArray("landmarks"),
        frame.sourcePacket.getJSONArray("worldLandmarks"), if (mode == ReplayMode.IMAGE) 0 else frame.sourceFrameId, 1.25)
    val plan = ReplayPlan(ReplayMode.VIDEO, ReplayDelegate.CPU)
    val report = ReplayRunner.run(source, plan, gate, ticket, factory = { model, settings ->
        calls += model to settings
        object : ReplayInference {
            override fun infer(frame: ReplayFrame) = fake(frame, settings.mode)
            override fun close() { closed++ }
        }
    })
    check(calls.map { it.first } == listOf(ReplayModel.LITE, ReplayModel.FULL) && calls.all { it.second == plan })
    check(closed == 2)
    check(source.frames.map { it.sourcePacket.toString() } == inputBefore)
    check(!report.getBoolean("oscOutputEnabled") && !report.getBoolean("originalLiveStreamReconstructed"))
    check(report.getJSONArray("cases").getJSONObject(0).getJSONArray("results").getJSONObject(0).getLong("sourceFrameId") == 100L)
    gate.finish(ticket)

    val gpuTicket = gate.begin()
    var failedGpuCases = 0
    val gpu = ReplayRunner.run(source, ReplayPlan(delegate = ReplayDelegate.GPU), gate, gpuTicket,
        factory = { _, settings ->
            check(settings.delegate == ReplayDelegate.GPU); failedGpuCases++
            throw IllegalStateException("Synthetic unavailable GPU")
        })
    check(failedGpuCases == 2)
    repeat(2) {
        val case = gpu.getJSONArray("cases").getJSONObject(it)
        check(case.getString("status") == "error" && !case.getBoolean("fallbackUsed"))
        check(case.getString("errorMessage") == "Synthetic unavailable GPU")
        check(!case.has("configuredDelegate") && case.getJSONArray("results").length() == 0)
    }
    gate.finish(gpuTicket)

    val stopping = gate.begin()
    var cancelledClose = false
    rejected {
        ReplayRunner.run(source, ReplayPlan(), gate, stopping, factory = { _, settings ->
            object : ReplayInference {
                override fun infer(frame: ReplayFrame): ReplaySample { gate.cancel(); return fake(frame, settings.mode) }
                override fun close() { cancelledClose = true }
            }
        })
    }
    check(cancelledClose && !gate.publish(stopping) { error("Published after stop") })
    rejected { gate.begin() } // Resources must be released before restarting.
    gate.finish(stopping)
    val newer = gate.begin()
    gate.finish(stopping)
    check(gate.current(newer) && !gate.publish(stopping) { error("Published stale generation") })
    gate.finish(newer)
    rejected { ReplaySample(false, points, points, 0, 0.0).result(source.frames[0], ReplayMode.IMAGE) }
    rejected { fake(source.frames[0], ReplayMode.IMAGE).result(source.frames[0], ReplayMode.VIDEO) }
    for (sentinel in listOf(-1L, Long.MIN_VALUE / 1000)) {
        val imageSentinel = ReplaySample(true, points, points, sentinel, 1.0)
            .result(source.frames[0], ReplayMode.IMAGE)
        check(imageSentinel.isNull("taskResultTimestampMs") && imageSentinel.getLong("frameworkTimestampMs") == sentinel)
    }

    // Real saved images may be parsed on the host. Inference remains explicitly synthetic.
    if (args.size == 2) {
        val real = ReplayArchive.read(File(args[0]).readBytes())
        val fixtureGate = ReplayGate()
        val fixtureTicket = fixtureGate.begin()
        val fixture = ReplayRunner.run(real, ReplayPlan(), fixtureGate, fixtureTicket, factory = { _, settings ->
            object : ReplayInference {
                override fun infer(frame: ReplayFrame) = fake(frame, settings.mode)
                override fun close() { }
            }
        }).put("runtime", JSONObject().put("synthetic", true).put("applicationId", "com.vrchattrack.replay")
            .put("internetPermission", false).put("cameraPermission", false).put("appVersion", "host-check"))
        File(args[1]).apply { check(!exists()); parentFile.mkdirs(); writeText(fixture.toString()) }
        println("HOST_PARSED_REAL_CAPTURE frames=${real.frames.size}; zipSha256=${real.zipSha256}; synthetic inference fixture only")
    }
    println("Replay checks passed: bounded ZIP/schema/PNG integrity, identity/order, no second mirror, two models, no GPU fallback, error/missing data, close/cancel and stale publication")
}
