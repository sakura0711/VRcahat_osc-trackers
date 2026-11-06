package com.vrchattrack.replay

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.zip.CRC32
import java.util.zip.ZipInputStream

fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes)
    .joinToString("") { "%02x".format(it.toInt() and 255) }

data class ReplayFrame(val index: Int, val sourceFrameId: Long, val imageSha256: String,
                       val width: Int, val height: Int, val rotation: Int, val mirrored: Boolean,
                       val png: ByteArray, val sourcePacket: JSONObject) {
    fun identity(): JSONObject = JSONObject().put("index", index).put("sourceFrameId", sourceFrameId)
        .put("imageSha256", imageSha256).put("imageWidth", width).put("imageHeight", height)
        .put("inputRotationDegrees", rotation).put("mirroredInput", mirrored)
}

data class ReplaySource(val zipSha256: String, val captureSession: String, val appVersion: String,
                        val frames: List<ReplayFrame>)

internal fun JSONObject.integer(key: String): Long {
    val value = get(key)
    require(value is Int || value is Long) { "Expected integer: $key" }
    return (value as Number).toLong().also { require(it >= 0) { "Negative integer: $key" } }
}

internal fun JSONObject.boolean(key: String): Boolean = get(key).also {
    require(it is Boolean) { "Expected boolean: $key" }
} as Boolean

internal fun validatePoints(points: JSONArray, count: Int) {
    require(points.length() == count) { "Landmark count mismatch" }
    for (i in 0 until count) {
        val point = points.getJSONObject(i)
        for (axis in listOf("x", "y", "z")) {
            val value = point.get(axis)
            require(value is Number && value.toDouble().isFinite()) { "Invalid coordinate" }
        }
        for (key in listOf("visibility", "presence")) {
            if (!point.isNull(key)) {
                val value = point.get(key)
                require(value is Number && value.toDouble().isFinite() && value.toDouble() in 0.0..1.0) {
                    "Invalid confidence"
                }
            }
        }
    }
}

/** Reads only into bounded memory; no archive entry is extracted to a filesystem. */
object ReplayArchive {
    const val MAX_ZIP_BYTES = 80 * 1024 * 1024
    const val MAX_IMAGE_BYTES = 8 * 1024 * 1024

    fun read(bytes: ByteArray, cancelled: () -> Boolean = { false }): ReplaySource {
        require(bytes.isNotEmpty() && bytes.size <= MAX_ZIP_BYTES) { "ZIP too large or empty" }
        val files = linkedMapOf<String, ByteArray>()
        var total = 0L
        var entries = 0
        ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
            while (true) {
                if (cancelled()) throw ReplayCancelled()
                val entry = zip.nextEntry ?: break
                require(++entries <= 200) { "Too many ZIP entries" }
                val name = entry.name
                if (entry.isDirectory) {
                    require(name.matches(Regex("frame-[0-9]{4}/"))) { "Unsafe ZIP directory" }
                    // nextEntry() otherwise drains directory payloads outside
                    // the bounded file loop. Reject any payload after one byte.
                    require(zip.read() == -1) { "ZIP directory must be empty" }
                    continue
                }
                require(name == "manifest.json" || name.matches(Regex("frame-[0-9]{4}/(input.png|landmarks.json)"))) {
                    "Unexpected ZIP path"
                }
                require(!files.containsKey(name) && files.size < 81) { "Duplicate or excessive ZIP entries" }
                val limit = when {
                    name == "manifest.json" -> 64 * 1024
                    name.endsWith(".png") -> MAX_IMAGE_BYTES
                    else -> 256 * 1024
                }
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    if (cancelled()) throw ReplayCancelled()
                    val count = zip.read(buffer)
                    if (count < 0) break
                    total += count
                    require(output.size().toLong() + count <= limit && total <= MAX_ZIP_BYTES) { "ZIP expansion limit" }
                    output.write(buffer, 0, count)
                }
                files[name] = output.toByteArray()
            }
        }
        val manifest = JSONObject(requireNotNull(files["manifest.json"]).toString(Charsets.UTF_8))
        require(manifest.getString("format") == "vrchat-track-image-pairs" && manifest.integer("version") == 1L)
        val session = manifest.getString("captureSession").also { require(it.isNotBlank() && it.length <= 128) }
        val metadata = files.keys.filter { it.endsWith("/landmarks.json") }
        require(metadata.size in 1..40 && files.size == metadata.size * 2 + 1) { "Incomplete pairs" }
        val frames = metadata.map { name ->
            if (cancelled()) throw ReplayCancelled()
            require(name.substring(6, 10).toInt() in 1..40) { "Invalid capture index" }
            val meta = JSONObject(files.getValue(name).toString(Charsets.UTF_8))
            require(meta.getString("format") == "vrchat-track-image-pair" && meta.integer("version") == 1L)
            require(meta.getString("captureSession") == session) { "Capture session mismatch" }
            val packet = meta.getJSONObject("packet")
            require(packet.integer("version") == 1L)
            val id = meta.integer("frameId")
            require(packet.integer("resultTimestampMs") == id) { "Frame ID mismatch" }
            packet.integer("captureMonotonicNs")
            require(packet.integer("analysisStartMonotonicNs") > 0)
            require(packet.getString("modelAsset").isNotBlank())
            val rotationValue = packet.integer("inputRotationDegrees")
            require(rotationValue in listOf(0L, 90L, 180L, 270L))
            val rotation = rotationValue.toInt()
            val mirror = packet.boolean("mirroredInput")
            val png = requireNotNull(files[name.substringBefore('/') + "/input.png"])
            val image = meta.getJSONObject("image")
            require(image.getString("file") == "input.png")
            val sha = sha256(png)
            require(image.getString("sha256") == sha) { "Image hash mismatch" }
            val (width, height) = pngDimensions(png)
            require(packet.integer("imageWidth") == width.toLong() && packet.integer("imageHeight") == height.toLong()) {
                "Image dimensions mismatch"
            }
            val count = if (packet.boolean("personDetected")) 33 else 0
            validatePoints(packet.getJSONArray("landmarks"), count)
            validatePoints(packet.getJSONArray("worldLandmarks"), count)
            ReplayFrame(0, id, sha, width, height, rotation, mirror, png, packet)
        }.sortedBy { it.sourceFrameId }
        require(frames.map { it.sourceFrameId }.distinct().size == frames.size) { "Duplicate frame ID" }
        return ReplaySource(sha256(bytes), session, manifest.optString("appVersion", "unknown"),
                            frames.mapIndexed { i, frame -> frame.copy(index = i + 1) })
    }

    fun pngDimensions(data: ByteArray): Pair<Int, Int> {
        require(data.size in 45..MAX_IMAGE_BYTES && data.take(8).toByteArray().contentEquals(
            byteArrayOf(137.toByte(), 80, 78, 71, 13, 10, 26, 10))) { "Not a PNG" }
        fun unsigned(offset: Int) = ByteBuffer.wrap(data, offset, 4).int.toLong() and 0xffffffffL
        var offset = 8
        var dimensions: Pair<Int, Int>? = null
        var sawData = false
        while (offset.toLong() + 12 <= data.size) {
            val length = unsigned(offset)
            val end = offset.toLong() + 12 + length
            require(end <= data.size) { "Truncated PNG" }
            val kind = String(data, offset + 4, 4, Charsets.US_ASCII)
            val crc = CRC32().apply { update(data, offset + 4, length.toInt() + 4) }.value
            require(crc == unsigned(offset + 8 + length.toInt())) { "PNG CRC mismatch" }
            if (dimensions == null) {
                require(kind == "IHDR" && length == 13L) { "Missing IHDR" }
                val w = unsigned(offset + 8)
                val h = unsigned(offset + 12)
                require(w in 1..4_194_304L && h in 1..4_194_304L && w * h <= 4_194_304L) { "PNG pixel limit" }
                dimensions = w.toInt() to h.toInt()
            } else require(kind != "IHDR") { "Duplicate IHDR" }
            if (kind == "IDAT") sawData = true
            if (kind == "IEND") {
                require(length == 0L && end == data.size.toLong() && sawData) { "Invalid PNG end" }
                return dimensions
            }
            offset = end.toInt()
        }
        error("Incomplete PNG")
    }
}
