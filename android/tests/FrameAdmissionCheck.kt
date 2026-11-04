package com.vrchattrack.singlephone

fun main() {
    val admission = FrameAdmission()
    check(admission.accept(100L))
    check(admission.accept(102L))
    // Older callbacks must stay rejected even if the previously queued frame
    // has already been sent and the queue is empty.
    check(!admission.accept(101L))
    check(!admission.accept(102L))
    check(admission.accept(103L))
    check(FrameAdmission().accept(1L)) // A new sender has its own timeline.
    println("FrameAdmission checks passed")
}
