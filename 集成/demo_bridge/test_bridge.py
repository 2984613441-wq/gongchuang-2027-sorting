from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bridge import (
    Action,
    BridgeError,
    Detection,
    DetectionStabilizer,
    FaultLatchedError,
    MotionController,
    StabilityConfig,
    Timeouts,
    load_config,
    parse_inputs,
    parse_status,
    run_events,
)
from fake_serial import FakeSerial


IDLE = (
    "STATUS SAFE_LOCK=1 MOTION_TEST=1 SERVO_TEST=1 ARMED=0 MODE=0 "
    "STEP_AXIS=0 SERVO_ARMED=0 SERVO_ACTIVE=0 SERVO_US=0"
)
RUNNING_X = (
    "STATUS SAFE_LOCK=1 MOTION_TEST=1 SERVO_TEST=1 ARMED=0 MODE=3 "
    "STEP_AXIS=1 SERVO_ARMED=0 SERVO_ACTIVE=0 SERVO_US=0"
)


def normal_responder(command: str):
    responses = {
        "STOP ALL": ["OK STOP ALL"],
        "STATUS": [IDLE],
        "INPUTS": ["INPUTS RAW=01FF STABLE=01FF ACTIVE=0000"],
        "MOTION ARM": ["OK MOTION ARMED 10S"],
        "MOVE X DIR0": ["OK MOTION STARTING", RUNNING_X, IDLE],
    }
    return responses.get(command, [])


class DetectionTests(unittest.TestCase):
    def test_json_contract_is_strict(self):
        detection = Detection.from_json_line(
            '{"frame_id":1,"label":"class_a","confidence":0.9,"ts_ms":100}'
        )
        self.assertEqual(detection.label, "class_a")
        with self.assertRaises(BridgeError):
            Detection.from_json_line(
                '{"frame_id":1,"label":"class_a","confidence":0.9,'
                '"ts_ms":100,"bbox":[]}'
            )

    def test_consecutive_frames_latch_and_explicit_absence_releases(self):
        stabilizer = DetectionStabilizer(StabilityConfig(0.7, 3, 1000))
        self.assertIsNone(stabilizer.offer(Detection(1, "a", 0.9, 0)))
        self.assertIsNone(stabilizer.offer(Detection(2, "a", 0.6, 100)))
        self.assertIsNone(stabilizer.offer(Detection(3, "a", 0.9, 200)))
        self.assertIsNone(stabilizer.offer(Detection(4, "a", 0.9, 300)))
        self.assertEqual(stabilizer.offer(Detection(5, "a", 0.9, 400)), "a")
        self.assertTrue(stabilizer.latched)
        self.assertIsNone(stabilizer.offer(Detection(6, "a", 0.99, 500)))
        self.assertIsNone(stabilizer.offer(Detection(7, None, 0.0, 600)))
        self.assertIsNone(stabilizer.offer(Detection(8, None, 0.0, 1599)))
        self.assertTrue(stabilizer.latched)
        self.assertIsNone(stabilizer.offer(Detection(9, None, 0.0, 1600)))
        self.assertFalse(stabilizer.latched)
        self.assertIsNone(stabilizer.offer(Detection(10, "a", 0.9, 1700)))

    def test_duplicate_frame_does_not_advance_candidate(self):
        stabilizer = DetectionStabilizer(StabilityConfig(0.7, 2, 1000))
        self.assertIsNone(stabilizer.offer(Detection(1, "a", 0.9, 0)))
        self.assertIsNone(stabilizer.offer(Detection(1, "a", 0.9, 10)))
        self.assertIsNone(stabilizer.offer(Detection(2, "a", 0.9, 20)))
        self.assertEqual(stabilizer.offer(Detection(3, "a", 0.9, 30)), "a")


class ConfigTests(unittest.TestCase):
    def write_config(self, value):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "config.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return directory, path

    def test_example_actions_are_disabled(self):
        config = load_config(Path(__file__).with_name("config.example.json"))
        self.assertTrue(config.actions)
        self.assertTrue(all(not action.enabled for action in config.actions.values()))

    def test_invalid_axis_and_unknown_fields_fail(self):
        directory, path = self.write_config({
            "actions": {
                "a": {"enabled": True, "axis": "Z", "direction": "DIR0"}
            }
        })
        try:
            with self.assertRaises(BridgeError):
                load_config(path)
        finally:
            directory.cleanup()
        directory, path = self.write_config({"unexpected": True})
        try:
            with self.assertRaises(BridgeError):
                load_config(path)
        finally:
            directory.cleanup()

    def test_invalid_numeric_types_fail_cleanly(self):
        for value in (
            {"stability": {"consecutive_frames": "5"}},
            {"timeouts": {"ack_s": "soon"}},
            {"stability": {"min_confidence": True}},
        ):
            directory, path = self.write_config(value)
            try:
                with self.assertRaises(BridgeError):
                    load_config(path)
            finally:
                directory.cleanup()


class ParserTests(unittest.TestCase):
    def test_inputs_and_status(self):
        self.assertEqual(
            parse_inputs("INPUTS RAW=01FF STABLE=01FF ACTIVE=0000"), 0
        )
        self.assertEqual(
            parse_inputs("INPUTS RAW=01FE STABLE=01FE ACTIVE=0001"), 1
        )
        self.assertTrue(parse_status(IDLE))


class ControllerTests(unittest.TestCase):
    def make_controller(self, responder=normal_responder):
        fake = FakeSerial(responder)
        log = []
        controller = MotionController(fake, Timeouts(0.02, 0.02, 0.02), log.append)
        return fake, controller, log

    def test_success_transaction_order(self):
        fake, controller, log = self.make_controller()
        controller.execute(Action(True, "X", "DIR0"))
        self.assertEqual(fake.sent, [
            "STOP ALL", "STATUS", "INPUTS", "MOTION ARM", "MOVE X DIR0"
        ])
        self.assertFalse(controller.fault_latched)
        self.assertIn("ACTION COMPLETE", log)

    def test_active_input_latches_fault_and_never_sends_move(self):
        def responder(command):
            if command == "INPUTS":
                return ["INPUTS RAW=01FE STABLE=01FE ACTIVE=0001"]
            return normal_responder(command)

        fake, controller, _ = self.make_controller(responder)
        with self.assertRaises(FaultLatchedError):
            controller.execute(Action(True, "X", "DIR0"))
        self.assertTrue(controller.fault_latched)
        self.assertNotIn("MOTION ARM", fake.sent)
        self.assertNotIn("MOVE X DIR0", fake.sent)
        self.assertGreaterEqual(fake.sent.count("STOP ALL"), 2)

    def test_err_latches_fault_stops_and_does_not_retry_motion(self):
        def responder(command):
            if command == "MOTION ARM":
                return ["ERR MOTION_INHIBITED"]
            return normal_responder(command)

        fake, controller, _ = self.make_controller(responder)
        with self.assertRaises(FaultLatchedError):
            controller.execute(Action(True, "X", "DIR0"))
        self.assertTrue(controller.fault_latched)
        self.assertEqual(fake.sent.count("MOTION ARM"), 1)
        self.assertEqual(fake.sent.count("MOVE X DIR0"), 0)
        self.assertGreaterEqual(fake.sent.count("STOP ALL"), 2)

    def test_boot_during_motion_latches_fault(self):
        def responder(command):
            if command == "MOVE X DIR0":
                return ["OK MOTION STARTING", "BOOT SAFE HSI=16000000 SAFE_LOCK=1"]
            return normal_responder(command)

        fake, controller, _ = self.make_controller(responder)
        with self.assertRaises(FaultLatchedError):
            controller.execute(Action(True, "X", "DIR0"))
        self.assertTrue(controller.fault_latched)
        self.assertEqual(fake.sent.count("MOVE X DIR0"), 1)
        self.assertGreaterEqual(fake.sent.count("STOP ALL"), 2)

    def test_timeout_closes_transport_if_stop_is_unconfirmed(self):
        fake = FakeSerial(lambda command: [])
        controller = MotionController(fake, Timeouts(0.005, 0.005, 0.005),
                                      lambda value: None)
        with self.assertRaises(FaultLatchedError):
            controller.execute(Action(True, "X", "DIR0"))
        self.assertTrue(controller.fault_latched)
        self.assertTrue(fake.closed)
        self.assertNotIn("MOVE X DIR0", fake.sent)
        self.assertEqual(fake.sent.count("STOP ALL"), 4)


class RunEventTests(unittest.TestCase):
    def test_dry_run_and_disabled_action(self):
        from bridge import BridgeConfig

        detections = [
            Detection(1, "a", 1.0, 0),
            Detection(2, "a", 1.0, 100),
        ]
        outputs = []
        config = BridgeConfig(StabilityConfig(0.7, 2, 1000), Timeouts(), {
            "a": Action(True, "X", "DIR1")
        })
        self.assertEqual(run_events(detections, config, True, None, outputs.append), 0)
        self.assertEqual(outputs, ["DRY_RUN label=a action=MOVE X DIR1"])

        outputs.clear()
        disabled_config = BridgeConfig(StabilityConfig(0.7, 2, 1000), Timeouts(), {
            "a": Action(False, "X", "DIR1")
        })
        run_events(detections, disabled_config, True, None, outputs.append)
        self.assertEqual(outputs, ["IGNORED disabled label=a action=MOVE X DIR1"])


if __name__ == "__main__":
    unittest.main()
