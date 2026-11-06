package com.vrchattrack.singlephone

import java.io.File
import java.io.FilterOutputStream
import java.io.OutputStream
import java.security.MessageDigest
import java.util.UUID
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** No Android/network dependencies. A directory rename publishes a complete pair. */
class DiagnosticPairStore(private val root: File) {
    data class Session(val directory: File, val id: String)

    fun start(manifest: (String) -> String): Session {
        check(root.isDirectory || root.mkdirs()) { "Cannot create diagnostic storage" }
        val id = UUID.randomUUID().toString()
        val directory = File(root, "session-${System.currentTimeMillis()}-$id")
        check(directory.mkdir()) { "Cannot create diagnostic session" }
        File(directory, "manifest.json").writeText(manifest(id), Charsets.UTF_8)
        return Session(directory, id)
    }

    fun latest(): Session? = root.listFiles()?.filter {
        it.isDirectory && it.name.startsWith("session-") && File(it, "manifest.json").isFile
    }?.map { Session(it, it.name.takeLast(36)) }?.filter { completePairs(it).isNotEmpty() }
        ?.maxByOrNull { it.directory.name }

    fun completePairs(session: Session): List<File> = session.directory.listFiles()?.filter {
        it.isDirectory && it.name.matches(Regex("frame-[0-9]{4}")) &&
            File(it, "input.png").isFile && File(it, "landmarks.json").isFile
    }?.sortedBy { it.name } ?: emptyList()

    fun writePair(
        session: Session, index: Int, encode: (OutputStream) -> Unit,
        metadata: (String) -> String, publish: (() -> Unit) -> Boolean,
    ): Boolean {
        require(index in 1..40)
        val name = "frame-" + index.toString().padStart(4, '0')
        val pending = File(session.directory, ".$name.tmp")
        val destination = File(session.directory, name)
        check(!destination.exists() && pending.mkdir()) { "Diagnostic pair already exists" }
        try {
            val image = File(pending, "input.png")
            image.outputStream().use { stream ->
                val bounded = object : FilterOutputStream(stream) {
                    var bytes = 0L
                    override fun write(value: Int) {
                        check(++bytes <= MAX_IMAGE_BYTES) { "Diagnostic image too large" }
                        out.write(value)
                    }
                    override fun write(buffer: ByteArray, offset: Int, length: Int) {
                        bytes += length
                        check(bytes <= MAX_IMAGE_BYTES) { "Diagnostic image too large" }
                        out.write(buffer, offset, length)
                    }
                }
                encode(bounded)
                bounded.flush()
            }
            val digest = MessageDigest.getInstance("SHA-256")
            image.inputStream().use { stream ->
                val buffer = ByteArray(8192)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) break
                    digest.update(buffer, 0, count)
                }
            }
            val sha = digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
            File(pending, "landmarks.json").writeText(metadata(sha), Charsets.UTF_8)
            check(session.directory.walkTopDown().filter { it.isFile }.sumOf { it.length() } <= MAX_SESSION_BYTES) {
                "Diagnostic session storage limit reached"
            }
            return publish {
                check(!destination.exists() && pending.renameTo(destination)) { "Cannot publish diagnostic pair" }
            }
        } finally {
            // Only this known staging directory inside this session is removed.
            if (pending.exists()) pending.deleteRecursively()
        }
    }

    fun export(session: Session, output: OutputStream) {
        val pairs = completePairs(session)
        check(pairs.isNotEmpty()) { "No completed image pairs" }
        ZipOutputStream(output).use { zip ->
            val files = listOf(File(session.directory, "manifest.json")) +
                pairs.flatMap { listOf(File(it, "input.png"), File(it, "landmarks.json")) }
            for (file in files) {
                zip.putNextEntry(ZipEntry(file.relativeTo(session.directory).invariantSeparatorsPath))
                file.inputStream().use { it.copyTo(zip) }
                zip.closeEntry()
            }
        }
    }

    companion object {
        const val MAX_IMAGE_BYTES = 8L * 1024 * 1024
        const val MAX_SESSION_BYTES = 64L * 1024 * 1024
    }
}
