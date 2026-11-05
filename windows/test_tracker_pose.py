import math
import random
import copy
import unittest

from tracker_pose import SWAPPED_LANDMARKS, TrackerCalibrationConfig, TrackerPoseCalibrator, unit


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

    def test_explicit_side_swap_restores_physical_feet_and_yaw(self):
        def front_camera_frame(right_lift=0, turn=0):
            frame = pose(right_lift=right_lift, turn=turn)
            # Synthetic mirrored model labels and a declared camera depth axis.
            # Neither convention is inferred solely from the camera being front-facing.
            for point in frame["worldLandmarks"]:
                point["x"] *= -1
                point["z"] *= -1
            for field in ("landmarks", "worldLandmarks"):
                values = frame[field]
                frame[field] = [values[SWAPPED_LANDMARKS.get(i, i)] for i in range(33)]
            return frame

        old = TrackerPoseCalibrator(config(mirrored_input=True, forward_sign=1))
        calibrate(old, front_camera_frame())
        reversed_values = old.ingest(front_camera_frame(right_lift=0.3), 300_000_000)
        self.assertAlmostEqual(reversed_values["left_foot"].position[1], 0.38)

        fixed = TrackerPoseCalibrator(config(mirrored_input=True, forward_sign=-1, swap_left_right=True))
        calibrate(fixed, front_camera_frame())
        frame = front_camera_frame(right_lift=0.3)
        before = copy.deepcopy(frame)
        values = fixed.ingest(frame, 300_000_000)
        self.assertEqual(frame, before)
        self.assertAlmostEqual(values["right_foot"].position[1], 0.38)
        self.assertAlmostEqual(values["left_foot"].position[1], 0.08)
        self.assertLess(values["left_foot"].position[0], 0)
        self.assertGreater(values["right_foot"].position[0], 0)
        turned = fixed.ingest(front_camera_frame(turn=45), 400_000_000)
        self.assertAlmostEqual(turned["hip"].rotation[1], 45)

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
        self.assertEqual(controller.diagnostic.reason, "calibration_forward")

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
        self.assertEqual(controller.diagnostic.reason, "calibration_height_changed")

    def test_low_world_confidence_suppresses_complete_batch(self):
        controller = TrackerPoseCalibrator(config())
        calibrate(controller)
        bad = pose()
        bad["worldLandmarks"][31]["visibility"] = 0.1
        self.assertEqual(controller.ingest(bad, 300_000_000), {})
        self.assertEqual(controller.diagnostic.reason, "world_confidence")
        self.assertEqual(controller.diagnostic.landmarks, (31,))
        self.assertEqual(set(controller.ingest(pose(), 400_000_000)),
                         {"hip", "left_foot", "right_foot"})

    def test_diagnostic_lists_all_low_confidence_points(self):
        controller = TrackerPoseCalibrator(config())
        bad = pose()
        for index in (27, 29, 31):
            bad["landmarks"][index]["visibility"] = 0.1
        self.assertEqual(controller.ingest(bad, 0), {})
        self.assertEqual(controller.diagnostic.reason, "image_confidence")
        self.assertEqual(controller.diagnostic.landmarks, (27, 29, 31))

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

    def test_vertical_hip_axis_cannot_supply_heading(self):
        controller = TrackerPoseCalibrator(config())
        calibrate(controller)
        bad = pose()
        bad["worldLandmarks"][23].update(x=0.0, y=-0.13, z=0.0)
        bad["worldLandmarks"][24].update(x=0.0, y=0.13, z=0.0)
        self.assertEqual(controller.ingest(bad, 300_000_000), {})
        self.assertEqual(controller.diagnostic.reason, "hip_direction")

    def test_timeout_preserves_clock_until_explicit_reset(self):
        controller = TrackerPoseCalibrator(config())
        calibrate(controller)
        controller.tick(600_000_001)
        self.assertEqual(controller.ingest(pose(), 100_000_000), {})
        self.assertEqual(controller.samples, [])
        controller.reset()
        self.assertEqual(controller.ingest(pose(), 100_000_000), {})
        self.assertEqual(len(controller.samples), 1)

    def test_extreme_coordinates_and_clock_values_fail_closed(self):
        for coordinate in (1e308, 10 ** 1000, float("nan"), float("inf")):
            controller = TrackerPoseCalibrator(config())
            bad = pose()
            bad["worldLandmarks"][28]["x"] = coordinate
            with self.subTest(coordinate=str(coordinate)[:12]):
                self.assertEqual(controller.ingest(bad, 0), {})
                self.assertIsNone(controller.calibration)
        controller = TrackerPoseCalibrator(config())
        for moment in (-1, True, float("nan")):
            with self.subTest(moment=moment), self.assertRaises(ValueError):
                controller.tick(moment)

    def test_large_finite_vector_normalizes_without_overflow(self):
        direction = unit((1e308, 1e308, 0.0))
        self.assertIsNotNone(direction)
        self.assertAlmostEqual(math.hypot(*direction), 1.0)
        self.assertIsNone(unit((float("inf"), 0.0, 0.0)))

    def test_calibration_cancels_camera_rotation_scale_translation_and_mirror(self):
        randomizer = random.Random(20261105)
        for case in range(32):
            angles = [randomizer.uniform(-math.pi, math.pi) for _ in range(3)]
            model_scale = randomizer.uniform(0.8, 1.2)
            offset = [randomizer.uniform(-0.2, 0.2) for _ in range(3)]
            yaw = randomizer.uniform(-180, 180)
            mirrored = case % 2 == 0

            def camera_frame(right_lift=0.0):
                frame = pose(right_lift=right_lift)
                for point in frame["worldLandmarks"]:
                    x, y, z = (point[axis] for axis in ("x", "y", "z"))
                    # Apply an independent camera rotation about X, Y, then Z.
                    c, s = math.cos(angles[0]), math.sin(angles[0])
                    y, z = c * y - s * z, s * y + c * z
                    c, s = math.cos(angles[1]), math.sin(angles[1])
                    x, z = c * x + s * z, -s * x + c * z
                    c, s = math.cos(angles[2]), math.sin(angles[2])
                    x, y = c * x - s * y, s * x + c * y
                    x, y, z = (value * model_scale + shift for value, shift in zip((x, y, z), offset))
                    point.update(x=-x if mirrored else x, y=y, z=z)
                return frame

            with self.subTest(case=case):
                controller = TrackerPoseCalibrator(config(mirrored_input=mirrored, neutral_yaw_deg=yaw))
                calibrate(controller, camera_frame())
                values = controller.ingest(camera_frame(right_lift=0.3), 300_000_000)
                self.assertEqual(set(values), {"hip", "left_foot", "right_foot"})
                radians = math.radians(yaw)
                for role, lateral, height in (("hip", 0.0, 0.9), ("left_foot", -0.15, 0.08),
                                              ("right_foot", 0.15, 0.38)):
                    expected = (math.cos(radians) * lateral, height, -math.sin(radians) * lateral)
                    for actual, wanted in zip(values[role].position, expected):
                        self.assertAlmostEqual(actual, wanted, places=6)
                    self.assertAlmostEqual(values[role].rotation[1], yaw, places=6)

    def test_invalid_config_rejected(self):
        for changes in ({"standing_hip_height_m": float("nan")},
                        {"mirrored_input": None}, {"forward_sign": 0},
                        {"swap_left_right": "yes"},
                        {"minimum_samples": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config(**changes)


if __name__ == "__main__":
    unittest.main()
