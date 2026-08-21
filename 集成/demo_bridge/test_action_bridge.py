from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from action_bridge import (
    ActionBridgeConfig,
    ActionController,
    BridgeError,
    CommandAction,
    Detection,
    FaultLatchedError,
    StabilityConfig,
    Timeouts,
    load_action_config,
    run_action_events,
)
from fake_serial import FakeSerial


IDLE = (
    "STATUS SAFE_LOCK=1 MOTION_TEST=1 SERVO_TEST=1 ARMED=0 MODE=0 "
    "STEP_AXIS=0 STEP_TARGET=0 STEP_REMAIN=0 STEP_RESULT=0 "
    "SERVO_ARMED=0 SERVO_ACTIVE=0 SERVO_US=0 GROUP_TEST=1 "
    "GROUP_ARMED=0 GROUP_ACTIVE=0 GROUP_XDIR=0 GROUP_YDIR=0 "
    "GROUP_SERVO_US=0 BARRIER_TEST=1 BARRIER_ARMED=0 "
    "BARRIER_ACTIVE=0 BARRIER_MASK=0 BARRIER_US=0"
)
RUNNING_MOVE_X = IDLE.replace("ARMED=0 MODE=0 STEP_AXIS=0",
                              "ARMED=0 MODE=3 STEP_AXIS=1")
RUNNING_SERVO = IDLE.replace("SERVO_ARMED=0 SERVO_ACTIVE=0 SERVO_US=0",
                             "SERVO_ARMED=0 SERVO_ACTIVE=1 SERVO_US=1000")
RUNNING_GROUP = IDLE.replace("GROUP_ARMED=0 GROUP_ACTIVE=0",
                             "GROUP_ARMED=0 GROUP_ACTIVE=1")
RUNNING_BARRIER = IDLE.replace("BARRIER_ARMED=0 BARRIER_ACTIVE=0",
                               "BARRIER_ARMED=0 BARRIER_ACTIVE=1")


def responder_for(run_command: str, run_ok: str, running: str):
    responses = {
        "STOP ALL": ["OK STOP ALL"],
        "STATUS": [IDLE],
        "INPUTS": ["INPUTS RAW=01FF STABLE=01FF ACTIVE=0000"],
        "MOTION ARM": ["OK MOTION ARMED 10S"],
        "SERVO ARM": ["OK SERVO ARMED 10S"],
        "GROUP ARM": ["OK GROUP ARMED 10S"],
        "BARRIER ARM": ["OK BARRIER ARMED 10S"],
    }

    def responder(command: str):
        if command in responses:
            return responses[command]
        if command == run_command:
            return [run_ok, running, IDLE]
        return []

    return responder


class ActionConfigTests(unittest.TestCase):
    def write_config(self, value):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "config.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return directory, path

    def test_full_example_actions_are_disabled(self):
        config = load_action_config(
            Path(__file__).with_name("config.full.example.json")
        )
        self.assertTrue(config.actions)
        self.assertTrue(all(not action.enabled
                            for action in config.actions.values()))

    def test_invalid_kind_fails(self):
        directory, path = self.write_config({
            "actions": {"a": {"enabled": True, "kind": "teleport"}}
        })
        try:
            with self.assertRaises(BridgeError):
                load_action_config(path)
        finally:
            directory.cleanup()

    def test_move_steps_range_validation(self):
        for patch in ({"steps": 0}, {"steps": 1_000_001}, {"hz": 9},
                      {"hz": 10_001}):
            action = {
                "enabled": False, "kind": "move_steps", "axis": "X",
                "direction": "DIR0", "steps": 2000, "hz": 500
            }
            action.update(patch)
            directory, path = self.write_config(
                {"actions": {"a": action}}
            )
            try:
                with self.assertRaises(BridgeError):
                    load_action_config(path)
            finally:
                directory.cleanup()

    def test_barrier_channel_requires_channel(self):
        directory, path = self.write_config({
            "actions": {
                "a": {"enabled": False, "kind": "barrier",
                      "mode": "channel", "pulse_us": 1000}
            }
        })
        try:
            with self.assertRaises(BridgeError):
                load_action_config(path)
        finally:
            directory.cleanup()


class ActionCommandTests(unittest.TestCase):
    def test_command_strings_match_frozen_list(self):
        self.assertEqual(
            CommandAction(True, "move_steps",
                          {"axis": "X", "direction": "DIR0",
                           "steps": 2000, "hz": 500}).run_command,
            "MOVE X DIR0 STEPS 2000 HZ 500")
        self.assertEqual(
            CommandAction(True, "servo", {"pulse_us": 1000}).run_command,
            "SERVO PB10 P1000")
        self.assertEqual(
            CommandAction(True, "group",
                          {"xdir": "DIR0", "ydir": "DIR1",
                           "servo": "OPEN"}).run_command,
            "GROUP START XDIR0 YDIR1 OPEN")
        self.assertEqual(
            CommandAction(True, "barrier",
                          {"mode": "collect", "pulse_us": 1000}).run_command,
            "BARRIER COLLECT P1000")


class ActionControllerTests(unittest.TestCase):
    def make_controller(self, responder):
        fake = FakeSerial(responder)
        log = []
        controller = ActionController(fake, Timeouts(0.02, 0.02, 0.02),
                                      log.append)
        return fake, controller, log

    def test_move_steps_transaction_order(self):
        action = CommandAction(True, "move_steps",
                               {"axis": "X", "direction": "DIR0",
                                "steps": 2000, "hz": 500})
        fake, controller, log = self.make_controller(
            responder_for(action.run_command, action.run_ok, RUNNING_MOVE_X))
        controller.execute(action)
        self.assertEqual(fake.sent, [
            "STOP ALL", "STATUS", "INPUTS", "MOTION ARM", action.run_command
        ])
        self.assertFalse(controller.fault_latched)
        self.assertIn("ACTION COMPLETE", log)

    def test_servo_transaction_order(self):
        action = CommandAction(True, "servo", {"pulse_us": 1000})
        fake, controller, log = self.make_controller(
            responder_for(action.run_command, action.run_ok, RUNNING_SERVO))
        controller.execute(action)
        self.assertEqual(fake.sent, [
            "STOP ALL", "STATUS", "INPUTS", "SERVO ARM", action.run_command
        ])
        self.assertFalse(controller.fault_latched)

    def test_group_transaction_order(self):
        action = CommandAction(True, "group",
                               {"xdir": "DIR0", "ydir": "DIR1",
                                "servo": "OPEN"})
        fake, controller, log = self.make_controller(
            responder_for(action.run_command, action.run_ok, RUNNING_GROUP))
        controller.execute(action)
        self.assertEqual(fake.sent, [
            "STOP ALL", "STATUS", "INPUTS", "GROUP ARM", action.run_command
        ])
        self.assertFalse(controller.fault_latched)

    def test_barrier_transaction_order(self):
        action = CommandAction(True, "barrier",
                               {"mode": "collect", "pulse_us": 1000})
        fake, controller, log = self.make_controller(
            responder_for(action.run_command, action.run_ok, RUNNING_BARRIER))
        controller.execute(action)
        self.assertEqual(fake.sent, [
            "STOP ALL", "STATUS", "INPUTS", "BARRIER ARM", action.run_command
        ])
        self.assertFalse(controller.fault_latched)

    def test_err_latches_fault_and_never_retries(self):
        action = CommandAction(True, "move", {"axis": "X",
                                              "direction": "DIR0"})

        def responder(command):
            if command == "MOTION ARM":
                return ["ERR MOTION_INHIBITED"]
            return responder_for(action.run_command, action.run_ok,
                                 RUNNING_MOVE_X)(command)

        fake, controller, _ = self.make_controller(responder)
        with self.assertRaises(FaultLatchedError):
            controller.execute(action)
        self.assertTrue(controller.fault_latched)
        self.assertEqual(fake.sent.count("MOTION ARM"), 1)
        self.assertEqual(fake.sent.count(action.run_command), 0)
        self.assertGreaterEqual(fake.sent.count("STOP ALL"), 2)


class RunActionEventTests(unittest.TestCase):
    def test_dry_run_and_disabled_action(self):
        detections = [Detection(1, "a", 1.0, 0), Detection(2, "a", 1.0, 100)]
        outputs = []
        enabled = ActionBridgeConfig(StabilityConfig(0.7, 2, 1000),
                                     Timeouts(),
                                     {"a": CommandAction(
                                         True, "move",
                                         {"axis": "X", "direction": "DIR0"})})
        self.assertEqual(run_action_events(detections, enabled, True, None,
                                           outputs.append), 0)
        self.assertEqual(outputs,
                         ["DRY_RUN label=a action=MOVE X DIR0"])

        outputs.clear()
        disabled = ActionBridgeConfig(StabilityConfig(0.7, 2, 1000),
                                      Timeouts(),
                                      {"a": CommandAction(
                                          False, "move",
                                          {"axis": "X",
                                           "direction": "DIR0"})})
        run_action_events(detections, disabled, True, None, outputs.append)
        self.assertEqual(outputs,
                         ["IGNORED disabled label=a action=MOVE X DIR0"])


if __name__ == "__main__":
    unittest.main()
