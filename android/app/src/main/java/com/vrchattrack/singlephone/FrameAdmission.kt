package com.vrchattrack.singlephone

/** Rejects duplicate or older result timestamps even after the queue is drained. */
class FrameAdmission {
    private var latestMs: Long? = null

    // Caller holds the queue lock while checking and enqueuing.
    fun accept(timestampMs: Long): Boolean {
        val latest = latestMs
        if (latest != null && timestampMs <= latest) return false
        latestMs = timestampMs
        return true
    }
}
