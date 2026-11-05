import json
import socket
import sys
import threading
import time
import unittest

from pose_receiver import ReceiverStats, private_ipv4, serve, validate_packet


def packet(seq=1, detected=True, session="test-session"):
    point = {"x": 0.1, "y": 0.2, "z": -0.3, "visibility": 0.9, "presence": None}
    return {
        "version": 1,
        "session": session,
        "seq": seq,
        "captureMonotonicNs": 123,
        "analysisStartMonotonicNs": 125,
        "sendMonotonicNs": 456,
        "inferenceMs": 12.5,
        "personDetected": detected,
        "landmarks": [point.copy() for _ in range(33)] if detected else [],
        "worldLandmarks": [point.copy() for _ in range(33)] if detected else [],
    }


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


class ProtocolTests(unittest.TestCase):
    def test_rejects_incomplete_body_and_nonfinite_coordinates(self):
        incomplete = packet()
        incomplete["landmarks"].pop()
        with self.assertRaises(ValueError):
            validate_packet(encode(incomplete))
        bad_coordinate = packet()
        bad_coordinate["worldLandmarks"][3]["x"] = float("nan")
        with self.assertRaises(ValueError):
            validate_packet(encode(bad_coordinate))

    def test_no_pose_is_valid_only_with_empty_arrays(self):
        no_pose = packet(detected=False)
        self.assertFalse(validate_packet(encode(no_pose))["personDetected"])
        no_pose["landmarks"] = packet()["landmarks"]
        with self.assertRaises(ValueError):
            validate_packet(encode(no_pose))

    def test_order_gap_and_retired_session(self):
        stats = ReceiverStats()
        self.assertTrue(stats.observe(packet(5), "127.0.0.1", 1_000_000, 100))
        self.assertTrue(stats.observe(packet(8), "127.0.0.1", 2_000_000, 100))
        self.assertEqual(stats.missing, 2)
        self.assertFalse(stats.observe(packet(7), "127.0.0.1", 3_000_000, 100))
        self.assertTrue(stats.observe(packet(1, session="second"), "127.0.0.1", 4_000_000, 100))
        self.assertFalse(stats.observe(packet(9), "127.0.0.1", 5_000_000, 100))
        self.assertEqual(stats.out_of_order, 2)

    def test_summary_reports_pose_rate_processing_and_joint_confidence(self):
        stats = ReceiverStats()
        first = packet(seq=1)
        second = packet(seq=2)
        second["inferenceMs"] = 22.5
        second["landmarks"][15]["visibility"] = 0.1
        no_pose = packet(seq=3, detected=False)
        no_pose["inferenceMs"] = 99.0
        self.assertTrue(stats.observe(first, "127.0.0.1", 1_000_000_000, 100))
        self.assertTrue(stats.observe(second, "127.0.0.1", 2_000_000_000, 100))
        self.assertTrue(stats.observe(no_pose, "127.0.0.1", 3_000_000_000, 100))
        summary = stats.summary(3.0)
        self.assertEqual(summary["pose_frame_pct"], 66.67)
        self.assertEqual(summary["arrival_fps"], 1.0)
        self.assertEqual(summary["pose_arrival_fps"], 0.67)
        self.assertEqual(summary["phone_processing_p50_ms"], 12.5)
        self.assertEqual(summary["phone_processing_p95_ms"], 22.5)
        self.assertEqual(summary["joint_confident_pct"]["Puppet/LeftElbowFlex"], 50.0)
        self.assertEqual(summary["joint_confident_pct"]["Puppet/RightElbowFlex"], 100.0)
        self.assertEqual(summary["joint_confident_pct"]["Puppet/LeftArmRaise"], 100.0)

    def test_only_private_and_loopback_ipv4_addresses_are_allowed(self):
        self.assertTrue(private_ipv4("192.168.20.100"))
        self.assertTrue(private_ipv4("127.0.0.1"))
        self.assertFalse(private_ipv4("0.0.0.0"))
        self.assertFalse(private_ipv4("8.8.8.8"))
        self.assertFalse(private_ipv4("::1"))

    def test_udp_round_trip_returns_matching_ack(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", 0))
            worker = threading.Thread(target=serve, args=(server, 0.6, 10.0))
            worker.start()
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    client.settimeout(2)
                    client.sendto(encode(packet(seq=17)), server.getsockname())
                    raw, _ = client.recvfrom(4096)
                    ack = json.loads(raw)
                    self.assertEqual(ack["type"], "ack")
                    self.assertEqual(ack["seq"], 17)
                    self.assertEqual(ack["session"], "test-session")
                    self.assertEqual(ack["sendMonotonicNs"], 456)
            finally:
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())

    def test_oversized_datagram_does_not_stop_receiver(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            server.bind(("127.0.0.1", 0))
            client.settimeout(2)
            results = []
            worker = threading.Thread(target=lambda: results.append(serve(server, 0.5, 10.0)))
            worker.start()
            try:
                client.sendto(b"x" * 20_000, server.getsockname())
                client.sendto(encode(packet(seq=7)), server.getsockname())
                ack, _ = client.recvfrom(4096)
                self.assertEqual(json.loads(ack)["seq"], 7)
            finally:
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
            self.assertEqual(results[0].oversized, 1)
            self.assertEqual(results[0].accepted, 1)

    @unittest.skipUnless(sys.platform == "win32", "Windows reports UDP port unreachable on receive")
    def test_closed_udp_peer_does_not_stop_receiver(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            server.bind(("127.0.0.1", 0))
            client.bind(("127.0.0.1", 0))
            client.settimeout(2)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as unused:
                unused.bind(("127.0.0.1", 0))
                closed_peer = unused.getsockname()
            results = []
            worker = threading.Thread(target=lambda: results.append(serve(server, 0.7, 10.0)))
            worker.start()
            try:
                server.sendto(b"ack", closed_peer)
                time.sleep(0.15)
                client.sendto(encode(packet(seq=8)), server.getsockname())
                ack, _ = client.recvfrom(4096)
                self.assertEqual(json.loads(ack)["seq"], 8)
            finally:
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
            # Windows/firewall policy may suppress the ICMP notification. This
            # integration check verifies that the next real packet still works;
            # the exception branch is exercised deterministically below.
            self.assertEqual(results[0].accepted, 1)

    def test_reported_udp_reset_is_counted_and_next_packet_is_accepted(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            server.bind(("127.0.0.1", 0))
            client.settimeout(2)

            class ResetOnceSocket:
                reset = False

                def settimeout(self, value):
                    server.settimeout(value)

                def recvfrom(self, size):
                    if not self.reset:
                        self.reset = True
                        raise ConnectionResetError("controlled UDP reset")
                    return server.recvfrom(size)

                def sendto(self, data, address):
                    return server.sendto(data, address)

            results = []
            worker = threading.Thread(target=lambda: results.append(serve(ResetOnceSocket(), 0.3, 10.0)))
            worker.start()
            try:
                client.sendto(encode(packet(seq=9)), server.getsockname())
                self.assertEqual(json.loads(client.recvfrom(4096)[0])["seq"], 9)
            finally:
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
            self.assertEqual(results[0].udp_resets, 1)
            self.assertEqual(results[0].accepted, 1)


if __name__ == "__main__":
    unittest.main()
