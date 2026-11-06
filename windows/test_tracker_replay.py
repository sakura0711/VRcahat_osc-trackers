import contextlib
import hashlib
import io
import json
import queue
import socket
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from test_inspect_pose_pairs import make_zip, pair
from test_tracker_pose import config, pose
from test_tracker_probe import decode_message
from tracker_output import ROLES, TrackerOutput, TrackerTransform
from tracker_pose import SWAPPED_LANDMARKS
from tracker_replay import main, play, prepare, read_commands, validate_slots


def sources(front_camera=False):
    result = []
    for n in range(1, 6):
        value = pair(n * 3000)
        packet = pose(right_lift=0.2 if n == 4 else 0, turn=30 if n == 4 else 0)
        if front_camera:
            for point in packet["worldLandmarks"]:
                point["x"] *= -1
                point["z"] *= -1
            for field in ("landmarks", "worldLandmarks"):
                packet[field] = [packet[field][SWAPPED_LANDMARKS.get(i, i)] for i in range(33)]
        value["packet"].update(packet, mirroredInput=front_camera)
        result.append(value)
    return result


def settings(**changes):
    return config(calibration_seconds=0, max_sample_gap_ms=5000, loss_timeout_ms=5000, **changes)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def wait(self, duration):
        self.now += duration


class TrackerReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "capture.zip"
        make_zip(self.source, sources())
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def plan(self, **changes):
        return prepare(self.source, [1, 2, 3], (2, 4, 5), settings(), **changes)

    def arguments(self):
        return [str(self.source), "--calibration-frames", "1-3", "--stand-frame", "2",
                "--box-frame", "4", "--return-frame", "5", "--hip-height", ".9",
                "--mirror", "no", "--forward-sign", "1"]

    def test_same_source_calibration_preserves_known_height_and_does_not_mutate_zip(self):
        original = self.source.read_bytes()
        with mock.patch("socket.socket", side_effect=AssertionError("network opened")):
            plan = self.plan(expected_sha256=self.digest)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(plan.source_sha256, self.digest)
        self.assertEqual([p.source_frame_id for p in plan.poses], [6000, 12000, 15000])
        self.assertEqual(plan.summary()["height_gain"], 1)
        self.assertFalse(plan.summary()["live_tracking"])
        standing, raised, returned = (p.transforms for p in plan.poses)
        self.assertAlmostEqual(standing["hip"].position[1], 0.9)
        self.assertAlmostEqual(raised["right_foot"].position[1] - standing["right_foot"].position[1], 0.2)
        self.assertAlmostEqual(raised["left_foot"].position[1], standing["left_foot"].position[1])
        self.assertEqual(returned, standing)
        with self.assertRaises(TypeError):
            plan.poses[0].transforms["hip"] = standing["hip"]

    def test_explicit_front_camera_role_mapping_and_rotation_policies(self):
        make_zip(self.source, sources(front_camera=True))
        arguments = (self.source, [1, 2, 3], (2, 4, 5),
                     settings(mirrored_input=True, swap_left_right=True, forward_sign=-1))
        frozen = prepare(*arguments)
        recorded = prepare(*arguments, rotation_policy="recorded")
        for a, b in zip(frozen.poses, recorded.poses):
            for role in ROLES:
                self.assertEqual(a.transforms[role].position, b.transforms[role].position)
                self.assertEqual(a.transforms[role].rotation, frozen.poses[0].transforms[role].rotation)
        self.assertAlmostEqual(recorded.poses[1].transforms["hip"].rotation[1], 30)
        self.assertAlmostEqual(frozen.poses[1].transforms["right_foot"].position[1], 0.28)
        self.assertAlmostEqual(frozen.poses[1].transforms["left_foot"].position[1], 0.08)

    def test_invalid_source_selection_or_calibration_rejects_whole_plan(self):
        for neutral, phases, cfg in (([1, 2, 3], (2, 5, 4), settings()),
                                     ([1, 2, 4], (2, 4, 5), settings()),
                                     ([1, 2, 3], (2, 4, 6), settings()),
                                     ([1, 1, 2], (2, 4, 5), settings()),
                                     ([1, 2, 3], (2, 4, 5), settings(mirrored_input=True)),
                                     ([1, 2, 3], (2, 4, 5), settings(forward_sign=-1))):
            with self.subTest(neutral=neutral, phases=phases, cfg=cfg):
                with self.assertRaises(ValueError):
                    prepare(self.source, neutral, phases, cfg)
        for index in (1, 3):  # Bad neutral or bad raised frame, no previous frame reuse.
            frames = sources()
            frames[index]["packet"]["landmarks"][31]["visibility"] = 0.1
            make_zip(self.source, frames)
            with self.assertRaises(ValueError):
                self.plan()

    def test_default_cli_has_no_socket_and_report_never_overwrites(self):
        report = Path(self.directory.name) / "plan.json"
        with mock.patch("socket.socket", side_effect=AssertionError("network opened")), \
                contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(self.arguments() + ["--report", str(report)]), 0)
            first = report.read_bytes()
            self.assertEqual(main(self.arguments() + ["--report", str(report)]), 1)
        self.assertIn("INSPECTION_ONLY", output.getvalue())
        self.assertEqual(report.read_bytes(), first)
        self.assertEqual(json.loads(first)["source_sha256"], self.digest)

    def test_osc_requires_explicit_valid_roles_digest_and_timing_before_transport(self):
        ids = ["--hip-id", "1", "--left-foot-id", "4", "--right-foot-id", "3"]
        for extra in ([], ids, ids + ["--expect-sha256", "0" * 64],
                      ids + ["--expect-sha256", self.digest, "--right-foot-id", "4"],
                      ids + ["--expect-sha256", self.digest, "--hz", "nan"]):
            with self.subTest(extra=extra), mock.patch("tracker_replay.TrackerOutput") as output, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(self.arguments() + ["--osc"] + extra), 1)
                output.assert_not_called()
        for values in ((1, 4, 3), (1, 3, 4)):
            validate_slots(dict(zip(ROLES, values)))
        for values in ((True, 4, 3), (1, 4, 4), (0, 4, 3), (1, None, 3)):
            with self.assertRaises(ValueError):
                validate_slots(dict(zip(ROLES, values)))

    def test_one_cycle_repeats_stills_without_interpolation_then_restores_standing(self):
        plan = self.plan()
        clock, commands, sent, phases = Clock(), queue.SimpleQueue(), [], []
        commands.put("play")
        result = play(plan, lambda batch: sent.append(batch) or 6, commands,
                      hz=2, pose_seconds=1, observer=phases.append, clock=clock, wait=clock.wait)
        self.assertEqual(phases, ["standing", "right_box", "returned"])
        self.assertEqual(sent, [p.transforms for p in plan.poses for _ in range(2)] + [plan.poses[0].transforms])
        self.assertEqual(result, dict(reason="complete", updates=6, neutral_restore_sent=True, osc_datagrams=42))

    def test_holds_neutral_until_play_and_accepts_stand_quit_and_eof(self):
        plan = self.plan()
        clock, commands, sent, phases = Clock(), queue.SimpleQueue(), [], []

        def wait(duration):
            clock.wait(duration)
            if len(sent) == 2:
                commands.put("play")
            elif len(sent) == 5:
                commands.put("stand")
            elif len(sent) == 6:
                commands.put("quit")

        result = play(plan, lambda batch: sent.append(batch) or 6, commands, hz=2, pose_seconds=1,
                      observer=phases.append, clock=clock, wait=wait)
        self.assertEqual(phases, ["calibration_standing", "standing", "right_box", "calibration_standing"])
        self.assertEqual(sent[4], plan.poses[1].transforms)
        self.assertEqual(sent[5:], [plan.poses[0].transforms] * 2)
        self.assertEqual(result["reason"], "stopped")
        read_commands(io.StringIO("ignored\nPLAY\nstand\n"), commands)
        self.assertEqual([commands.get() for _ in range(3)], ["play", "stand", "quit"])

    def test_timeout_stall_and_external_stop_do_not_resume_a_raised_pose(self):
        plan = self.plan()
        for scenario in ("timeout", "stalled", "stopped"):
            with self.subTest(scenario=scenario):
                clock, sent, stop = Clock(), [], threading.Event()

                def wait(duration):
                    clock.wait(2 if scenario == "stalled" else duration)
                    if scenario == "stopped":
                        stop.set()

                result = play(plan, lambda batch: sent.append(batch) or 6, queue.SimpleQueue(),
                              hz=2, pose_seconds=1, max_seconds=1, clock=clock, wait=wait, stop=stop)
                # A 2 s gap also reaches a 1 s deadline. Give watchdog its own longer deadline below.
                self.assertEqual(result["reason"], "timeout" if scenario == "stalled" else scenario)
                self.assertTrue(all(batch == plan.poses[0].transforms for batch in sent))
        clock, commands, sent = Clock(), queue.SimpleQueue(), []
        commands.put("play")

        def delayed_wait(duration):
            # Stall only once the raised pose has really been sent.
            clock.wait(1 if sent[-1] == plan.poses[1].transforms else duration)

        result = play(plan, lambda batch: sent.append(batch) or 6, commands, hz=20,
                      pose_seconds=1, clock=clock, wait=delayed_wait)
        self.assertEqual(result["reason"], "stalled")
        self.assertEqual(sent[-2:], [plan.poses[1].transforms, plan.poses[0].transforms])

    def test_invalid_batches_and_interrupts_fail_without_reusing_bad_data(self):
        plan = self.plan()
        bad = dict(plan.poses[1].transforms)
        bad["right_foot"] = TrackerTransform((0, float("nan"), 0), (0, 0, 0))
        invalid = replace(plan, poses=(plan.poses[0], replace(plan.poses[1], transforms=bad), plan.poses[2]))
        send = mock.Mock(return_value=6)
        with self.assertRaises(ValueError):
            play(invalid, send, queue.SimpleQueue())
        send.assert_not_called()
        send = mock.Mock(side_effect=[5, 6])
        with self.assertRaisesRegex(RuntimeError, "incomplete tracker update"):
            play(plan, send, queue.SimpleQueue())
        self.assertEqual(send.call_count, 2)
        for error in (KeyboardInterrupt(), OSError("send failure"), RuntimeError("incomplete tracker update")):
            with self.subTest(error=error):
                send = mock.Mock(side_effect=[error, 6])
                with self.assertRaises(type(error)):
                    play(plan, send, queue.SimpleQueue())
                self.assertEqual(send.call_count, 2)
                self.assertEqual(send.call_args.args[0], plan.poses[0].transforms)

    def test_cli_closes_transport_on_playback_error(self):
        for error in (OSError("transport"), KeyboardInterrupt()):
            with self.subTest(error=error), mock.patch("tracker_replay.TrackerOutput") as output, \
                    mock.patch("tracker_replay.play", side_effect=error), \
                    mock.patch("tracker_replay.threading.Thread"), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = main(self.arguments() + ["--osc", "--expect-sha256", self.digest,
                              "--hip-id", "1", "--left-foot-id", "4", "--right-foot-id", "3"])
                self.assertEqual(result, 0 if isinstance(error, KeyboardInterrupt) else 1)
                output.return_value.close.assert_called_once()

    def test_calibrated_replay_over_isolated_udp_has_correct_role_addresses_and_height(self):
        plan = self.plan()
        # A real, ephemeral loopback receiver; never VRChat's port 9000.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(1)
            output = TrackerOutput(dict(hip=1, left_foot=4, right_foot=3), receiver.getsockname()[1])
            self.addCleanup(output.close)
            decoded = []

            def send(batch):
                count = output.send(batch)
                decoded.append(dict(decode_message(receiver.recvfrom(1024)[0]) for _ in range(6)))
                return count

            commands, clock = queue.SimpleQueue(), Clock()
            commands.put("play")
            result = play(plan, send, commands, hz=1, pose_seconds=1, clock=clock, wait=clock.wait)
        self.assertEqual(result["reason"], "complete")
        self.assertEqual(len(decoded), 4)
        self.assertEqual(set(decoded[0]), {f"/tracking/trackers/{n}/{kind}"
                                          for n in (1, 4, 3) for kind in ("position", "rotation")})
        right, left = "/tracking/trackers/3/position", "/tracking/trackers/4/position"
        self.assertAlmostEqual(decoded[1][right][1] - decoded[0][right][1], 0.2, places=6)
        self.assertEqual(decoded[1][left][1], decoded[0][left][1])
        self.assertEqual(decoded[2], decoded[0])
        self.assertEqual(decoded[3], decoded[0])


if __name__ == "__main__":
    unittest.main()
