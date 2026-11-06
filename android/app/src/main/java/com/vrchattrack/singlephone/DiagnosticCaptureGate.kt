package com.vrchattrack.singlephone

/** Opt-in sampling with one owned frame in flight and cancellable generations. */
class DiagnosticCaptureGate(
    private val durationNs: Long = 120_000_000_000L,
    private val intervalNs: Long = 3_000_000_000L,
    private val maximumFrames: Int = 40,
) {
    data class Ticket(val generation: Long, val index: Int, val resultTimestampMs: Long)

    private var generation = 0L
    private var enabled = false
    private var startNs = 0L
    private var lastNowNs = 0L
    private var nextSampleNs = 0L
    private var lastResultMs = -1L
    private var samples = 0
    private var inFlight: Ticket? = null

    init {
        require(durationNs > 0 && intervalNs > 0 && maximumFrames > 0)
    }

    @Synchronized fun start(nowNs: Long) {
        require(nowNs >= 0)
        generation++
        enabled = true
        startNs = nowNs
        lastNowNs = nowNs
        nextSampleNs = nowNs
        lastResultMs = -1
        samples = 0
        // Keep an old owned bitmap in flight until its worker releases it.
    }

    @Synchronized fun stop() {
        enabled = false
        generation++
    }

    private fun current(nowNs: Long): Boolean {
        if (nowNs < lastNowNs) return false
        lastNowNs = nowNs
        if (enabled && nowNs - startNs >= durationNs) enabled = false
        return enabled
    }

    @Synchronized fun isActive(nowNs: Long): Boolean = current(nowNs)

    @Synchronized fun reserve(nowNs: Long, resultTimestampMs: Long): Ticket? {
        if (!current(nowNs) || resultTimestampMs < 0 || resultTimestampMs <= lastResultMs ||
            inFlight != null || samples >= maximumFrames || nowNs < nextSampleNs
        ) return null
        val ticket = Ticket(generation, ++samples, resultTimestampMs)
        inFlight = ticket
        lastResultMs = resultTimestampMs
        nextSampleNs = nowNs + intervalNs
        return ticket
    }

    /** Stop and publication use the same lock: after stop returns no pair can publish. */
    @Synchronized fun publish(ticket: Ticket, nowNs: Long, action: () -> Unit): Boolean {
        if (!current(nowNs) || ticket != inFlight || ticket.generation != generation) return false
        action()
        return true
    }

    @Synchronized fun release(ticket: Ticket) {
        if (ticket == inFlight) {
            inFlight = null
            if (ticket.generation == generation && samples >= maximumFrames) enabled = false
        }
    }
}
