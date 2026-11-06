package com.vrchattrack.singlephone

import java.awt.image.BufferedImage
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.zip.ZipInputStream
import javax.imageio.ImageIO

fun main(args: Array<String>) {
    val gate = DiagnosticCaptureGate(durationNs = 100, intervalNs = 10, maximumFrames = 2)
    check(gate.reserve(0, 1) == null) // Disabled by default.
    gate.start(1000)
    val first = checkNotNull(gate.reserve(1000, 10))
    check(gate.reserve(1001, 11) == null) // One owned bitmap at a time.
    var published = 0
    check(gate.publish(first, 1001) { published++ })
    gate.release(first)
    check(gate.reserve(1005, 11) == null) // Sampling interval.
    check(gate.reserve(1010, 10) == null) // Duplicate callback timestamp.
    val second = checkNotNull(gate.reserve(1010, 12))
    check(gate.publish(second, 1011) { published++ })
    gate.release(second)
    check(!gate.isActive(1012) && gate.reserve(1020, 13) == null) // Frame limit.
    check(published == 2)

    gate.start(2000)
    val stopped = checkNotNull(gate.reserve(2000, 20))
    gate.stop()
    check(!gate.publish(stopped, 2001) { error("published after stop") })
    gate.start(2010)
    check(gate.reserve(2010, 21) == null) // An old worker still owns its bitmap.
    gate.release(stopped)
    val fresh = checkNotNull(gate.reserve(2011, 21))
    check(!gate.publish(stopped, 2012) { error("old generation published") })
    check(gate.publish(fresh, 2012) { published++ })
    gate.release(fresh)
    check(gate.reserve(2010, 22) == null) // Clock cannot go backwards.
    val expiring = checkNotNull(gate.reserve(2021, 22))
    check(!gate.publish(expiring, 2110) { error("expired capture published") })
    gate.release(expiring)
    check(!gate.isActive(2111))

    val scratch = Files.createTempDirectory("diagnostic-pair-test-").toFile().canonicalFile
    try {
        val store = DiagnosticPairStore(scratch)
        val session = store.start { id ->
            """{"format":"vrchat-track-image-pairs","version":1,"captureSession":"$id"}"""
        }
        val png = ByteArrayOutputStream().also { stream ->
            val image = BufferedImage(3, 2, BufferedImage.TYPE_INT_ARGB)
            image.setRGB(0, 0, 0xffff0000.toInt())
            image.setRGB(2, 1, 0xff0000ff.toInt())
            check(ImageIO.write(image, "png", stream))
        }.toByteArray()
        val sha = MessageDigest.getInstance("SHA-256").digest(png)
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        var observedSha = ""
        check(store.writePair(session, 1, { it.write(png) }, {
            observedSha = it
            """{"sha256":"$it","resultTimestampMs":11}"""
        }, { action -> action(); true }))
        check(observedSha == sha)
        store.start { "{}" } // An empty latest attempt must not hide the last complete capture.
        check(store.latest()?.id == session.id)
        val complete = store.completePairs(session)
        check(complete.size == 1)
        check(File(complete[0], "input.png").readBytes().contentEquals(png))
        check(store.writePair(session, 2, { it.write(png) }, { "{}" }, { false }).not())
        check(!File(session.directory, ".frame-0002.tmp").exists())
        try {
            store.writePair(session, 3, { throw IllegalStateException("encoder failed") }, { "{}" }, { true })
            error("encoding failure was ignored")
        } catch (_: IllegalStateException) { }
        check(!File(session.directory, ".frame-0003.tmp").exists())
        try {
            store.writePair(session, 4, { it.write(ByteArray(DiagnosticPairStore.MAX_IMAGE_BYTES.toInt() + 1)) },
                            { "{}" }, { true })
            error("oversized image accepted")
        } catch (_: IllegalStateException) { }
        check(!File(session.directory, ".frame-0004.tmp").exists())
        try {
            store.writePair(session, 1, { it.write(byteArrayOf(1)) }, { "{}" }, { true })
            error("overwrote a completed pair")
        } catch (_: IllegalStateException) { }
        check(File(complete[0], "input.png").readBytes().contentEquals(png))
        val archive = ByteArrayOutputStream()
        store.export(session, archive)
        val names = mutableListOf<String>()
        ZipInputStream(ByteArrayInputStream(archive.toByteArray())).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                names += entry.name
                zip.readBytes()
            }
        }
        check(names == listOf("manifest.json", "frame-0001/input.png", "frame-0001/landmarks.json"))

        // A cross-language fixture from the real Kotlin pair store for the Windows reader.
        if (args.isNotEmpty()) {
            val fixtureRoot = File(args[0]).absoluteFile
            val fixtureStore = DiagnosticPairStore(fixtureRoot)
            val fixture = fixtureStore.start { id ->
                """{"format":"vrchat-track-image-pairs","version":1,"captureSession":"$id","appVersion":"synthetic-test"}"""
            }
            val points = (0 until 33).joinToString(",", "[", "]") {
                """{"x":0.5,"y":0.5,"z":0.0,"visibility":0.9,"presence":0.9}"""
            }
            check(fixtureStore.writePair(fixture, 1, { it.write(png) }, { hash ->
                """{"format":"vrchat-track-image-pair","version":1,"captureSession":"${fixture.id}","frameId":11,"image":{"file":"input.png","sha256":"$hash"},"packet":{"version":1,"resultTimestampMs":11,"captureMonotonicNs":1001,"analysisStartMonotonicNs":1002,"inferenceMs":10.0,"personDetected":true,"imageWidth":3,"imageHeight":2,"inputRotationDegrees":90,"mirroredInput":true,"modelAsset":"synthetic-test","landmarks":$points,"worldLandmarks":$points}}"""
            }, { action -> action(); true }))
            File(fixtureRoot, "fixture-path.txt").writeText(fixture.directory.absolutePath)
            File(fixtureRoot, "fixture.zip").outputStream().use { fixtureStore.export(fixture, it) }
        }
        println("Diagnostic capture checks passed: opt-in, interval/limit, stale/expired generations, bounded ownership, atomic pairs, hashes, failed writes, no overwrite and ZIP export")
    } finally {
        check(scratch.name.startsWith("diagnostic-pair-test-") &&
            scratch.parentFile.canonicalFile == File(System.getProperty("java.io.tmpdir")).canonicalFile)
        scratch.deleteRecursively()
    }
}
