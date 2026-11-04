package com.vrchattrack.singlephone

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.SystemClock
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.Closeable
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.PortUnreachableException
import java.net.SocketException
import java.net.SocketTimeoutException
import java.nio.charset.StandardCharsets
import java.util.ArrayDeque
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.ceil
import kotlin.math.round

data class LanStatus(
    val sent: Long,
    val acknowledged: Long,
    val overwritten: Long,
    val expired: Long,
    val rttP50Ms: Double?,
    val rttP95Ms: Double?,
    val hasRecentAck: Boolean,
    val lastBytes: Int,
)

/**
 * Sends only the latest pose to one RFC1918 IPv4 peer. ACK RTT uses the phone's
 * elapsedRealtime clock at both ends; no PC/phone clock subtraction is performed.
 * The camera image is never sent or stored.
 */
class LanPoseSender(
    private val context: Context,
    private val host: String,
    private val port: Int,
    private val listener: Listener,
) : Closeable {
    interface Listener {
        fun onStatus(status: LanStatus)
        fun onError(message: String)
    }

    private val running = AtomicBoolean(false)
    private val queue = ArrayBlockingQueue<PoseFrame>(1)
    private val frameAdmission = FrameAdmission()
    private val pending = ConcurrentHashMap<Long, Long>()
    private val session = UUID.randomUUID().toString()
    private val lastPublishMs = AtomicLong(0)
    private val lock = Any()
    private val rtts = ArrayDeque<Double>()
    @Volatile private var socket: DatagramSocket? = null
    @Volatile private var senderThread: Thread? = null
    @Volatile private var receiverThread: Thread? = null
    private var sent = 0L
    private var acknowledged = 0L
    private var overwritten = 0L
    private var expired = 0L
    private var lastAckNs = 0L
    private var lastBytes = 0

    fun start() {
        check(running.compareAndSet(false, true)) { "sender already started" }
        senderThread = Thread(::sendLoop, "pose-udp-send").also { it.start() }
    }

    fun offer(frame: PoseFrame) {
        if (!running.get()) return
        synchronized(queue) {
            if (!frameAdmission.accept(frame.captureTimestampMs)) {
                synchronized(lock) { overwritten += 1 }
                return
            }
            if (!queue.offer(frame)) {
                queue.poll()
                synchronized(lock) { overwritten += 1 }
                queue.offer(frame)
            }
        }
    }

    private fun sendLoop() {
        try {
            val address = privateIpv4(host)
            require(port in 1..65535) { "UDP 埠號必須介於 1–65535" }
            val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            @Suppress("DEPRECATION")
            val wifi = connectivity.allNetworks.firstOrNull { network ->
                connectivity.getNetworkCapabilities(network)
                    ?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
            } ?: throw IllegalStateException("手機尚未連接 Wi-Fi")
            val datagram = DatagramSocket()
            socket = datagram
            wifi.bindSocket(datagram)
            datagram.connect(address, port)
            datagram.soTimeout = RECEIVE_TIMEOUT_MS
            receiverThread = Thread({ receiveLoop(datagram) }, "pose-udp-ack").also { it.start() }
            Log.i(TAG, "UDP started host=$host port=$port")
            var seq = 0L
            while (running.get()) {
                val frame = queue.poll(250, TimeUnit.MILLISECONDS)
                val nowNs = SystemClock.elapsedRealtimeNanos()
                expireOld(nowNs)
                if (frame != null) {
                    if (frame.analysisStartMonotonicNs != null &&
                        nowNs - frame.analysisStartMonotonicNs > MAX_FRAME_AGE_NS
                    ) {
                        synchronized(lock) { overwritten += 1 }
                    } else {
                        val nextSeq = seq + 1
                        val packet = buildPosePacket(frame, nextSeq)
                        val sendNs = SystemClock.elapsedRealtimeNanos()
                        packet.put("sendMonotonicNs", sendNs)
                        val bytes = packet.toString().toByteArray(StandardCharsets.UTF_8)
                        require(bytes.size <= MAX_DATAGRAM_BYTES) { "姿勢資料超過封包大小上限" }
                        pending[nextSeq] = sendNs
                        try {
                            datagram.send(DatagramPacket(bytes, bytes.size))
                            seq = nextSeq
                            synchronized(lock) {
                                sent += 1
                                lastBytes = bytes.size
                            }
                        } catch (error: PortUnreachableException) {
                            pending.remove(nextSeq)
                            Log.w(TAG, "Receiver is not accepting UDP yet")
                        }
                    }
                }
                publishIfDue()
            }
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        } catch (error: Exception) {
            if (running.get()) {
                Log.e(TAG, "UDP sender failed", error)
                listener.onError(error.message ?: error.javaClass.simpleName)
            }
        } finally {
            running.set(false)
            socket?.close()
            socket = null
            pending.clear()
        }
    }

    private fun receiveLoop(datagram: DatagramSocket) {
        val buffer = ByteArray(MAX_ACK_BYTES)
        while (running.get()) {
            try {
                val packet = DatagramPacket(buffer, buffer.size)
                datagram.receive(packet)
                val nowNs = SystemClock.elapsedRealtimeNanos()
                val ack = JSONObject(String(packet.data, packet.offset, packet.length, StandardCharsets.UTF_8))
                if (ack.optInt("version", -1) != VERSION || ack.optString("type") != "ack" ||
                    ack.optString("session") != session
                ) continue
                val seq = ack.optLong("seq", -1L)
                val sendNs = pending[seq] ?: continue
                if (ack.optLong("sendMonotonicNs", -1L) != sendNs || !pending.remove(seq, sendNs)) continue
                val delta = nowNs - sendNs
                if (delta < 0L || delta > ACK_TIMEOUT_NS) continue
                synchronized(lock) {
                    acknowledged += 1
                    lastAckNs = nowNs
                    if (rtts.size >= MAX_RTT_SAMPLES) rtts.removeFirst()
                    rtts.addLast(delta / NANOS_PER_MS)
                }
                publishIfDue()
            } catch (_: SocketTimeoutException) {
                publishIfDue()
            } catch (_: PortUnreachableException) {
                publishIfDue()
            } catch (_: SocketException) {
                if (running.get()) listener.onError("Wi-Fi UDP socket 已關閉")
                break
            } catch (error: Exception) {
                Log.w(TAG, "Ignored invalid ACK", error)
            }
        }
    }

    private fun expireOld(nowNs: Long) {
        pending.forEach { (seq, sendNs) ->
            if (nowNs - sendNs > ACK_TIMEOUT_NS && pending.remove(seq, sendNs)) {
                synchronized(lock) { expired += 1 }
            }
        }
    }

    private fun publishIfDue() {
        val nowMs = SystemClock.uptimeMillis()
        val previous = lastPublishMs.get()
        if (nowMs - previous < STATUS_INTERVAL_MS || !lastPublishMs.compareAndSet(previous, nowMs)) return
        val nowNs = SystemClock.elapsedRealtimeNanos()
        val status = synchronized(lock) {
            val sorted = rtts.toList().sorted()
            LanStatus(
                sent = sent,
                acknowledged = acknowledged,
                overwritten = overwritten,
                expired = expired,
                rttP50Ms = percentile(sorted, 0.50),
                rttP95Ms = percentile(sorted, 0.95),
                hasRecentAck = lastAckNs > 0L && nowNs - lastAckNs <= RECENT_ACK_NS,
                lastBytes = lastBytes,
            )
        }
        listener.onStatus(status)
        Log.i(
            TAG,
            String.format(
                Locale.US,
                "UDP sent=%d ack=%d overwritten=%d expired=%d rttP50Ms=%s rttP95Ms=%s bytes=%d recentAck=%b",
                status.sent, status.acknowledged, status.overwritten, status.expired,
                status.rttP50Ms?.let { String.format(Locale.US, "%.2f", it) } ?: "none",
                status.rttP95Ms?.let { String.format(Locale.US, "%.2f", it) } ?: "none",
                status.lastBytes, status.hasRecentAck,
            ),
        )
    }

    private fun buildPosePacket(frame: PoseFrame, seq: Long): JSONObject {
        val points = JSONArray()
        val worldPoints = JSONArray()
        if (frame.poseDetected) {
            require(frame.landmarks.size == PoseFrame.LANDMARK_COUNT &&
                frame.worldLandmarks.size == PoseFrame.LANDMARK_COUNT) { "姿勢資料不完整" }
            frame.landmarks.forEach { point ->
                points.put(pointJson(point.x, point.y, point.z, point.visibility, point.presence))
            }
            frame.worldLandmarks.forEach { point ->
                worldPoints.put(pointJson(point.x, point.y, point.z, point.visibility, point.presence))
            }
        }
        return JSONObject()
            .put("version", VERSION)
            .put("session", session)
            .put("seq", seq)
            .put("captureMonotonicNs", frame.cameraTimestampNs ?: 0L)
            .put("captureTimestampSource", "camera-device-unspecified")
            .put("analysisStartMonotonicNs", frame.analysisStartMonotonicNs ?: 0L)
            .put("inferenceMs", frame.timing?.totalMs ?: frame.inferenceMs.toDouble())
            .put("personDetected", frame.poseDetected)
            .put("landmarks", points)
            .put("worldLandmarks", worldPoints)
    }

    private fun pointJson(x: Float, y: Float, z: Float, visibility: Float?, presence: Float?): JSONObject =
        JSONObject()
            .put("x", rounded(x))
            .put("y", rounded(y))
            .put("z", rounded(z))
            .put("visibility", visibility?.let(::rounded) ?: JSONObject.NULL)
            .put("presence", presence?.let(::rounded) ?: JSONObject.NULL)

    private fun rounded(value: Float): Double {
        require(value.isFinite()) { "姿勢資料包含無效數值" }
        return round(value.toDouble() * COORDINATE_SCALE) / COORDINATE_SCALE
    }

    override fun close() {
        running.set(false)
        socket?.close()
        senderThread?.interrupt()
        receiverThread?.interrupt()
        queue.clear()
    }

    companion object {
        private const val TAG = "LanPoseSender"
        private const val VERSION = 1
        private const val MAX_DATAGRAM_BYTES = 16_384
        private const val MAX_ACK_BYTES = 1_024
        private const val MAX_RTT_SAMPLES = 512
        private const val RECEIVE_TIMEOUT_MS = 500
        private const val STATUS_INTERVAL_MS = 1_000L
        private const val ACK_TIMEOUT_NS = 5_000_000_000L
        private const val RECENT_ACK_NS = 3_000_000_000L
        private const val MAX_FRAME_AGE_NS = 1_000_000_000L
        private const val NANOS_PER_MS = 1_000_000.0
        private const val COORDINATE_SCALE = 10_000.0

        fun privateIpv4(host: String): Inet4Address {
            val parts = host.trim().split(".")
            require(parts.size == 4 && parts.all { it.isNotEmpty() && it.all(Char::isDigit) }) {
                "請輸入電腦的私人 IPv4 位址"
            }
            val octets = parts.map { it.toIntOrNull() ?: -1 }
            require(octets.all { it in 0..255 }) { "IPv4 位址格式錯誤" }
            val allowed = octets[0] == 10 ||
                (octets[0] == 172 && octets[1] in 16..31) ||
                (octets[0] == 192 && octets[1] == 168)
            require(allowed) { "只允許私人區網 IPv4 位址" }
            return InetAddress.getByAddress(octets.map { it.toByte() }.toByteArray()) as Inet4Address
        }

        private fun percentile(sorted: List<Double>, fraction: Double): Double? {
            if (sorted.isEmpty()) return null
            val index = (ceil(fraction * sorted.size).toInt() - 1).coerceIn(0, sorted.lastIndex)
            return sorted[index]
        }
    }
}
