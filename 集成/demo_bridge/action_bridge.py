"""Generic JSONL vision-to-STM32 bridge for the frozen ASCII command list.

This module extends bridge.py with the full command set from
docs/design/2026-08-20-motion-command-list-v1.md:
MOVE, MOVE STEPS, SERVO, GROUP, BARRIER.

Safety model is the same as bridge.py: every action defaults to disabled,
the CLI defaults to dry-run, motion requires --allow-motion, and any protocol
failure latches a fault that only manual recovery can clear.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from bridge import (
    BridgeError,
    Detection,
    DetectionStabilizer,
    FaultLatchedError,
    PySerialTransport,
    StabilityConfig,
    Timeouts,
    jsonl_events,
    manual_detections,
    parse_inputs,
    parse_status,
)


_AXIS_INDEX = {"X": 1, "Y": 2, "Z": 3}
_DIRECTIONS = {"DIR0", "DIR1"}
_KINDS = {"move", "move_steps", "servo", "group", "barrier"}
_BARRIER_MODES = {"all", "channel", "collect", "avoid"}
_PULSE_MIN_US = 500
_PULSE_MAX_US = 2500


@dataclass(frozen=True)
class CommandAction:
    enabled: bool
    kind: str
    params: Mapping[str, Any]

    @property
    def arm_command(self) -> str:
        if self.kind in {"move", "move_steps"}:
            return "MOTION ARM"
        if self.kind == "servo":
            return "SERVO ARM"
        if self.kind == "group":
            return "GROUP ARM"
        if self.kind == "barrier":
            return "BARRIER ARM"
        raise BridgeError(f"unsupported action kind: {self.kind}")

    @property
    def arm_ok(self) -> str:
        if self.kind in {"move", "move_steps"}:
            return "OK MOTION ARMED 10S"
        if self.kind == "servo":
            return "OK SERVO ARMED 10S"
        if self.kind == "group":
            return "OK GROUP ARMED 10S"
        if self.kind == "barrier":
            return "OK BARRIER ARMED 10S"
        raise BridgeError(f"unsupported action kind: {self.kind}")

    @property
    def run_command(self) -> str:
        if self.kind == "move":
            axis = self.params["axis"]
            direction = self.params["direction"]
            return f"MOVE {axis} {direction}"
        if self.kind == "move_steps":
            axis = self.params["axis"]
            direction = self.params["direction"]
            steps = self.params["steps"]
            hz = self.params["hz"]
            return f"MOVE {axis} {direction} STEPS {steps} HZ {hz}"
        if self.kind == "servo":
            return f"SERVO PB10 P{self.params['pulse_us']}"
        if self.kind == "group":
            xdir = self.params["xdir"]
            ydir = self.params["ydir"]
            servo = self.params["servo"]
            return f"GROUP START X{xdir} Y{ydir} {servo}"
        if self.kind == "barrier":
            mode = self.params["mode"]
            pulse = self.params["pulse_us"]
            if mode == "all":
                return f"BARRIER P{pulse}"
            if mode == "channel":
                return f"BARRIER {self.params['channel']} P{pulse}"
            if mode == "collect":
                return f"BARRIER COLLECT P{pulse}"
            if mode == "avoid":
                return f"BARRIER AVOID P{pulse}"
        raise BridgeError(f"unsupported action kind: {self.kind}")

    @property
    def run_ok(self) -> str:
        if self.kind in {"move", "move_steps"}:
            return "OK MOTION STARTING"
        if self.kind == "servo":
            return "OK SERVO STARTING 2S"
        if self.kind == "group":
            return "OK GROUP STARTING"
        if self.kind == "barrier":
            mode = self.params["mode"]
            return {
                "all": "OK BARRIER SET ALL",
                "channel": "OK BARRIER SET CHANNEL",
                "collect": "OK BARRIER COLLECT",
                "avoid": "OK BARRIER AVOID",
            }[mode]
        raise BridgeError(f"unsupported action kind: {self.kind}")

    def is_running(self, status: Mapping[str, int]) -> bool:
        if self.kind in {"move", "move_steps"}:
            return (status.get("MODE") == 3 and
                    status.get("STEP_AXIS") == _AXIS_INDEX[self.params["axis"]])
        if self.kind == "servo":
            return status.get("SERVO_ACTIVE") == 1
        if self.kind == "group":
            return status.get("GROUP_ACTIVE") == 1
        if self.kind == "barrier":
            return status.get("BARRIER_ACTIVE") == 1
        return False


@dataclass(frozen=True)
class ActionBridgeConfig:
    stability: StabilityConfig = field(default_factory=StabilityConfig)
    timeouts: Timeouts = field(default_factory=Timeouts)
    actions: Mapping[str, CommandAction] = field(default_factory=dict)


def _reject_unknown(value: Mapping[str, Any], allowed: set[str],
                    context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BridgeError(f"unknown {context} fields: {unknown}")


def _require_fields(value: Mapping[str, Any], required: set[str],
                    context: str) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise BridgeError(f"{context} missing fields: {missing}")


def _require_bool(value: Mapping[str, Any], name: str, context: str) -> bool:
    raw = value.get(name)
    if isinstance(raw, bool):
        return raw
    raise BridgeError(f"{context} {name} must be boolean")


def _require_int(value: Mapping[str, Any], name: str, context: str,
                 minimum: int, maximum: int) -> int:
    raw = value.get(name)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise BridgeError(f"{context} {name} must be an integer")
    if not minimum <= raw <= maximum:
        raise BridgeError(f"{context} {name} must be in [{minimum}, {maximum}]")
    return raw


def _require_str(value: Mapping[str, Any], name: str, context: str,
                 choices: Optional[set[str]] = None) -> str:
    raw = value.get(name)
    if not isinstance(raw, str) or not raw.strip():
        raise BridgeError(f"{context} {name} must be a non-empty string")
    raw = raw.strip()
    if choices is not None and raw not in choices:
        raise BridgeError(f"{context} {name} must be one of {sorted(choices)}")
    return raw


def _parse_action(label: str, raw: Any) -> CommandAction:
    if not isinstance(label, str) or not label.strip():
        raise BridgeError("action label must be a non-empty string")
    if not isinstance(raw, dict):
        raise BridgeError(f"action {label!r} must be an object")
    _reject_unknown(raw, {"enabled", "kind", "axis", "direction", "steps",
                          "hz", "pulse_us", "xdir", "ydir", "servo",
                          "mode", "channel"}, f"action {label!r}")
    _require_fields(raw, {"enabled", "kind"}, f"action {label!r}")
    enabled = _require_bool(raw, "enabled", f"action {label!r}")
    kind = _require_str(raw, "kind", f"action {label!r}", _KINDS)
    params: dict[str, Any] = {}
    context = f"action {label!r}"

    if kind in {"move", "move_steps"}:
        _require_fields(raw, {"axis", "direction"}, context)
        params["axis"] = _require_str(raw, "axis", context, set(_AXIS_INDEX))
        params["direction"] = _require_str(raw, "direction", context,
                                           _DIRECTIONS)
        if kind == "move_steps":
            _require_fields(raw, {"steps", "hz"}, context)
            params["steps"] = _require_int(raw, "steps", context, 1, 1_000_000)
            params["hz"] = _require_int(raw, "hz", context, 10, 10_000)
    elif kind == "servo":
        _require_fields(raw, {"pulse_us"}, context)
        params["pulse_us"] = _require_int(raw, "pulse_us", context,
                                          _PULSE_MIN_US, _PULSE_MAX_US)
    elif kind == "group":
        _require_fields(raw, {"xdir", "ydir", "servo"}, context)
        params["xdir"] = _require_str(raw, "xdir", context, _DIRECTIONS)
        params["ydir"] = _require_str(raw, "ydir", context, _DIRECTIONS)
        params["servo"] = _require_str(raw, "servo", context, {"OPEN", "CLOSE"})
    elif kind == "barrier":
        _require_fields(raw, {"mode", "pulse_us"}, context)
        params["mode"] = _require_str(raw, "mode", context, _BARRIER_MODES)
        params["pulse_us"] = _require_int(raw, "pulse_us", context,
                                          _PULSE_MIN_US, _PULSE_MAX_US)
        if params["mode"] == "channel":
            params["channel"] = _require_int(raw, "channel", context, 1, 4)
    return CommandAction(enabled, kind, params)


def load_action_config(path: str | Path) -> ActionBridgeConfig:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot load config: {exc}") from exc
    if not isinstance(raw, dict):
        raise BridgeError("config root must be an object")
    _reject_unknown(raw, {"stability", "timeouts", "actions"}, "config")

    stability_raw = raw.get("stability", {})
    if not isinstance(stability_raw, dict):
        raise BridgeError("stability must be an object")
    _reject_unknown(stability_raw,
                    {"min_confidence", "consecutive_frames", "release_after_ms"},
                    "stability")
    stability = StabilityConfig(**stability_raw)
    if (not isinstance(stability.min_confidence, (int, float)) or
            isinstance(stability.min_confidence, bool)):
        raise BridgeError("min_confidence must be numeric")
    if not 0.0 <= float(stability.min_confidence) <= 1.0:
        raise BridgeError("min_confidence must be between 0 and 1")
    if stability.consecutive_frames < 1:
        raise BridgeError("consecutive_frames must be at least 1")
    if stability.release_after_ms < 0:
        raise BridgeError("release_after_ms must be non-negative")

    timeouts_raw = raw.get("timeouts", {})
    if not isinstance(timeouts_raw, dict):
        raise BridgeError("timeouts must be an object")
    _reject_unknown(timeouts_raw, {"ack_s", "running_s", "idle_s"},
                    "timeouts")
    timeouts = Timeouts(**timeouts_raw)
    for name in ("ack_s", "running_s", "idle_s"):
        value = getattr(timeouts, name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise BridgeError(f"{name} must be numeric")
        if value <= 0:
            raise BridgeError(f"{name} must be positive")

    actions_raw = raw.get("actions", {})
    if not isinstance(actions_raw, dict):
        raise BridgeError("actions must be an object")
    actions: dict[str, CommandAction] = {}
    for label, action_raw in actions_raw.items():
        actions[label] = _parse_action(label, action_raw)
    return ActionBridgeConfig(stability, timeouts, actions)


def is_idle_status(status: Mapping[str, int]) -> bool:
    fields = {
        "ARMED", "MODE", "STEP_AXIS", "SERVO_ARMED", "SERVO_ACTIVE",
        "GROUP_ARMED", "GROUP_ACTIVE", "BARRIER_ARMED", "BARRIER_ACTIVE",
    }
    return all(status.get(name, 0) == 0 for name in fields)


class ActionController:
    """Executes a single CommandAction as a locked transaction."""

    def __init__(self, transport: Any, timeouts: Timeouts,
                 logger: Callable[[str], None] = print):
        self.transport = transport
        self.timeouts = timeouts
        self.logger = logger
        self.fault_latched = False
        self.fault_reason: Optional[str] = None

    def _write(self, line: str) -> None:
        self.logger(f"TX {line}")
        try:
            self.transport.write_line(line)
        except Exception as exc:
            raise BridgeError(f"serial write failed: {exc}") from exc

    def _read_until(self, predicate: Callable[[str], bool], timeout_s: float,
                    context: str, fatal: bool = True) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                line = self.transport.read_line(deadline)
            except Exception as exc:
                raise BridgeError(f"serial read failed: {exc}") from exc
            if line is None:
                continue
            line = line.strip()
            if not line:
                continue
            self.logger(f"RX {line}")
            if fatal and line.startswith("BOOT SAFE"):
                raise BridgeError("STM32 reset detected")
            if fatal and line.startswith("ERR "):
                raise BridgeError(f"STM32 rejected command: {line}")
            if predicate(line):
                return line
        raise BridgeError(f"timeout waiting for {context}")

    def _expect_exact(self, command: str, response: str) -> str:
        self._write(command)
        return self._read_until(lambda line: line == response,
                                self.timeouts.ack_s, response)

    def _confirm_idle(self, fatal: bool = True) -> None:
        self._write("STATUS")

        def idle(line: str) -> bool:
            status = parse_status(line)
            return status is not None and is_idle_status(status)

        self._read_until(idle, self.timeouts.ack_s, "idle STATUS",
                         fatal=fatal)

    def _baseline_stop(self) -> None:
        self._expect_exact("STOP ALL", "OK STOP ALL")
        self._confirm_idle()

    def execute(self, action: CommandAction) -> None:
        if self.fault_latched:
            raise FaultLatchedError(f"fault is latched: {self.fault_reason}")
        if not action.enabled:
            raise BridgeError("disabled action cannot be executed")
        try:
            self._baseline_stop()
            self._write("INPUTS")

            def inputs_clear(line: str) -> bool:
                active = parse_inputs(line)
                if active is None:
                    return False
                if active != 0:
                    raise BridgeError(f"motion inhibited: ACTIVE={active:04X}")
                return True

            self._read_until(inputs_clear, self.timeouts.ack_s,
                             "INPUTS ACTIVE=0000")
            self._expect_exact(action.arm_command, action.arm_ok)
            self._expect_exact(action.run_command, action.run_ok)

            def running(line: str) -> bool:
                status = parse_status(line)
                return status is not None and action.is_running(status)

            self._read_until(running, self.timeouts.running_s,
                             f"running {action.kind}")
            self._read_until(lambda line: parse_status(line) is not None and
                             is_idle_status(parse_status(line)),
                             self.timeouts.idle_s, "action completion")
            self.logger("ACTION COMPLETE")
        except BridgeError as exc:
            self.latch_fault(str(exc))
            raise FaultLatchedError(str(exc)) from exc

    def latch_fault(self, reason: str) -> bool:
        self.fault_latched = True
        self.fault_reason = reason
        self.logger(f"FAULT {reason}")
        stopped = False
        for _ in range(3):
            try:
                self._write("STOP ALL")
                self._read_until(lambda line: line == "OK STOP ALL",
                                 self.timeouts.ack_s, "OK STOP ALL",
                                 fatal=False)
                self._confirm_idle(fatal=False)
                stopped = True
                break
            except BridgeError:
                continue
        if not stopped:
            self.logger("FAULT STOP UNCONFIRMED - PHYSICAL POWER CUT REQUIRED")
            try:
                self.transport.close()
            except Exception:
                pass
        return stopped

    def emergency_stop(self, reason: str = "operator interrupt") -> bool:
        return self.latch_fault(reason)


def run_action_events(
    events: Iterable[Detection],
    config: ActionBridgeConfig,
    dry_run: bool,
    controller: Optional[ActionController],
    output: Callable[[str], None] = print,
) -> int:
    stabilizer = DetectionStabilizer(config.stability)
    for detection in events:
        label = stabilizer.offer(detection)
        if label is None:
            continue
        action = config.actions.get(label)
        if action is None:
            output(f"IGNORED unmapped label={label}")
            continue
        if not action.enabled:
            output(f"IGNORED disabled label={label} action={action.run_command}")
            continue
        if dry_run:
            output(f"DRY_RUN label={label} action={action.run_command}")
            continue
        if controller is None:
            raise BridgeError("action controller is required")
        controller.execute(action)
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="bridge JSON config")
    parser.add_argument("--port", help="STM32 serial port, for example COM17")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--allow-motion", action="store_true",
                        help="explicitly allow configured real motion")
    parser.add_argument("--dry-run", action="store_true",
                        help="never open serial or send commands (default)")
    parser.add_argument("--manual-label",
                        help="inject enough stable frames for one label")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_argument_parser().parse_args(argv)
    controller: Optional[ActionController] = None
    try:
        config = load_action_config(args.config)
        dry_run = args.dry_run or not args.allow_motion
        if args.allow_motion and args.dry_run:
            raise BridgeError("--allow-motion and --dry-run cannot be combined")
        if not dry_run:
            if not args.port:
                raise BridgeError("--port is required with --allow-motion")
            transport = PySerialTransport(args.port, args.baudrate)
            controller = ActionController(transport, config.timeouts,
                                          logger=lambda value: print(
                                              value, file=sys.stderr))
        events = (manual_detections(args.manual_label, config.stability)
                  if args.manual_label else jsonl_events(sys.stdin))
        return run_action_events(events, config, dry_run, controller)
    except KeyboardInterrupt:
        if controller is not None:
            controller.emergency_stop()
        print("interrupted; STOP ALL attempted", file=sys.stderr)
        return 130
    except BridgeError as exc:
        if controller is not None and not controller.fault_latched:
            controller.latch_fault(str(exc))
        print(f"bridge error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
