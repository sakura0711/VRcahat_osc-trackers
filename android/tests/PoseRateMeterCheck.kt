package com.vrchattrack.singlephone

fun main() {
    val meter = PoseRateMeter(periodNs = 1_000_000_000L)
    check(meter.record(0L, true) == null)
    repeat(9) { index ->
        check(meter.record((index + 1) * 100_000_000L, index < 7) == null)
    }
    check(meter.record(1_000_000_000L, true) == PoseRateWindow(1_000_000_000L, 10, 8))
    // A long callback gap must reduce measured throughput rather than disappear.
    check(meter.record(4_000_000_000L, false) == PoseRateWindow(3_000_000_000L, 1, 0))
    // A reset monotonic clock starts a new window instead of reporting negatives.
    check(meter.record(10L, true) == null)
    check(meter.record(1_000_000_010L, true) == PoseRateWindow(1_000_000_000L, 1, 1))
    println("PoseRateMeter checks passed")
}
