package com.vrchattrack.singlephone

/** Counts completed result callbacks, not camera frames or frames sent over Wi-Fi. */
data class PoseRateWindow(val durationNs: Long, val results: Int, val poses: Int)

class PoseRateMeter(private val periodNs: Long = 1_000_000_000L) {
    private var startNs: Long? = null
    private var results = 0
    private var poses = 0

    @Synchronized
    fun record(nowNs: Long, poseDetected: Boolean): PoseRateWindow? {
        val start = startNs
        if (start == null || nowNs < start) {
            startNs = nowNs
            results = 0
            poses = 0
            return null
        }
        results += 1
        if (poseDetected) poses += 1
        val elapsed = nowNs - start
        if (elapsed < periodNs) return null
        val window = PoseRateWindow(elapsed, results, poses)
        startNs = nowNs
        results = 0
        poses = 0
        return window
    }
}
