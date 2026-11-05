import math
import unittest

from tracker_pose import TrackerCalibrationConfig, TrackerPoseCalibrator


def pose(*, mirrored=False, right_lift=0.0, squat=0.0, turn=0.0):
    points = [(0.0, 0.0, 0.0) for _ in range(33)]
    for side, indices in ((-1, (11, 23, 27, 29, 31)), (1, (12, 24, 28, 30, 32))):
        shoulder, hip, ankle, heel, toe = indices
        lift = right_lift if side == 1 else 0.0
        points[shoulder] = (side * 0.20, 0.40 - squat, 0.0)
        points[hip] = (side * 0.13, 0.0, 0.0)
        points[ankle] = (side * 0.15, -0.82 + squat + lift, 0.0)
        points[heel] = (side * 0.15, -0.90 + squat + lift, -0.06)
        points[toe] = (side * 0.15, -0.90 + squat + lift, 0.16)
    radians = math.radians(turn)
    rotated = [
        (math.cos(radians) * x + math.sin(radians) * z,
         y,
         -math.sin(radians) * x + math.cos(radians) * z)
        for x, y, z in points
    ]
    if mirrored:
        rotated = [(-x, y, z) for x, y, z in rotated]
    world = [dict(zip(("x", "y", "z"), point)) for point in rotated]
    normalized = [dict(x=0.5, y=0.5, z=0.0, visibility=0.99, presence=0.99) for _ in range(33)]
    return {"personDetected": True, "landmarks": normalized, "worldLandmarks": world}


def config(**changes):
    values = dict(standing_hip_height_m=0.9, neutral_yaw_deg=0.0,
                  mirrored_input=False, forward_sign=1, calibration_seconds=0.2,
                  minimum_samples=3)
    values.update(changes)
    return TrackerCalibrationConfig(**values)


def calibrate(controller, frame=None, start_ns=0):
    frame = frame or pose()
    for moment in (start_ns, start_ns + 100_000_000, start_ns + 200_000_000):
        assert controller.ingest(frame, moment) == {}
    assert controller.calibration is not None


class TrackerPoseTests(unittest.TestCase):
    def test_standing_raised_foot_squat_and_turn(self):
        controller = TrackerPoseCalibrator(config())
        calibrate(controller)
        standing = controller.ingest(pose(), 300_000_000)
        self.assertEqual(set(standing), {"hip", "left_foot", "right_foot"})
        self.assertAlmostEqual(standing["hip"].position[1], 0.9)
        self.assertAlmostEqual(standing["left_foot"].position[1], 0.08)
        self.assertAlmostEqual(standing["left_foot"].position[0], -0.15)
        lifted = controller.ingest(pose(right_lift=0.3), 400_000_000)
        self.assertAlmostEqual(lifted["right_foot"].position[1], 0.38)
        self.assertAlmostEqual(lifted["left_foot"].position[1], 0.08)
        self.assertAlmostEqual(lifted["hip"].position[1], 0.9)
        squat = controller.ingest(pose(squat=0.25), 500_000_000)
        self.assertAlmostEqual(squat["hip"].position[1], 0.65)
        turned = controller.ingest(pose(turn=90), 600_000_000)
        self.assertAlmostEqual(turned["hip"].rotation[1], 90)
        self.assertAlmostEqual(turned["left_foot"].rotation[1], 90)

    def test_mirror_and_initial_yaw_are_explicit(self):
        controller = TrackerPoseCalibrator(config(mirrored_input=True, neutral_yaw_deg=30))
        calibrate(controller, pose(mirrored=True))
        transforms = controller.ingest(pose(mirrored=True), 300_000_000)
        self.assertAlmostEqual(transforms["hip"].rotation[1], 30)
        self.assertAlmostEqual(transforms["left_foot"].rotation[1], 30)
        self.assertAlmostEqual(transforms["left_foot"].position[0], -0.15 * math.cos(math.radians(30)))

    def test_no_transform_before_calibration_or_with_missing_points(self):
        controller = TrackerPoseCalibrator(config())
        self.assertEqual(controller.ingest(pose(right_lift=0.3), 0), {})
        self.assertIsNone(controller.calibration)
        calibrate(controller, start_ns=100_000_000)
        bad = pose()
        bad["landmarks"][31]["visibility"] = 0.1
        self.assertEqual(controller.ingest(bad, 400_000_000), {})
        self.assertEqual(controller.ingest(pose(), 500_000_000).keys(),
                         {"hip", "left_foot", "right_foot"})

    def test_wrong_forward_sign_cannot_calibrate(self):
        controller = TrackerPoseCalibrator(config(forward_sign=-1))
        for moment in (0, 100_000_000, 200_000_000):
            self.assertEqual(controller.ingest(pose(), moment), {})
        self.assertIsNone(controller.calibration)
        self.assertEqual(controller.samples, [])

    def test_turning_during_neutral_window_cannot_calibrate(self):
        controller = TrackerPoseCalibrator(config())
        for moment, turn in ((0, 0), (100_000_000, 90), (200_000_000, 0)):
            self.assertEqual(controller.ingest(pose(turn=turn), moment), {})
        self.assertIsNone(controller.calibration)
        self.assertEqual(controller.samples, [])

    def test_crouching_during_neutral_window_cannot_calibrate(self):
        controller = TrackerPoseCalibrator(config())
        for moment, squat in ((0, 0.0), (100_000_000, 0.2), (200_000_000, 0.0)):
            self.assertEqual(controller.ingest(pose(squat=squat), moment), {})
        self.assertIsNone(controller.calibration)
        self.assertEqual(controller.samples, [])

    def test_low_world_confidence_suppresses_complete_batch(self):
        controller = TrackerPoseCalibrator(config())
        calibrate(controller)
        bad = pose()
        bad["worldLandmarks"][31]["visibility"] = 0.1
        self.assertEqual(controller.ingest(bad, 300_000_000), {})
        self.assertEqual(set(controller.ingest(pose(), 400_000_000)),
                         {"hip", "left_foot", "right_foot"})

    def test_timeout_requires_new_calibration(self):
        controller = TrackerPoseCalibrator(config())
        calibrate(controller)
        self.assertTrue(controller.ingest(pose(), 300_000_000))
        controller.tick(600_000_001)
        self.assertIsNone(controller.calibration)
        self.assertEqual(controller.ingest(pose(), 700_000_000), {})
        self.assertIsNone(controller.calibration)

    def test_implausible_foot_position_does_not_extend_tracking(self):
        controller = TrackerPoseCalibrator(config())
        calibrate(controller)
        self.assertTrue(controller.ingest(pose(), 300_000_000))
        bad = pose()
        bad["worldLandmarks"][28]["x"] = 3.0
        self.assertEqual(controller.ingest(bad, 400_000_000), {})
        controller.tick(550_000_001)
        self.assertIsNone(controller.calibration)

    def test_invalid_config_rejected(self):
        for changes in ({"standing_hip_height_m": float("nan")},
                        {"mirrored_input": None}, {"forward_sign": 0},
                        {"minimum_samples": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config(**changes)


if __name__ == "__main__":
    unittest.main()
