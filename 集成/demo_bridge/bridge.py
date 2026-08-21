"""Minimal JSONL vision-to-STM32 demonstration bridge.

This module deliberately uses the existing diagnostic ASCII commands.  It is
not an implementation of the project's formal binary protocol.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional


class BridgeError(RuntimeError):
    """A protocol, safety, configuration, or transport failure."""


class FaultLatchedError(BridgeError):
    """The bridge entered a fault that requires manual recovery."""


@dataclass(frozen=True)
class Detection:
    frame_id: int
    label: Optional[str]
    confidence: float
    ts_ms: int

    @classmethod
    def from_json_line(cls, line: str) -> "Detection":
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"invalid JSONL detection: {exc}") from exc
        if not isinstance(value, dict):
            raise BridgeError("detection must be a JSON object")
        required = {"frame_id", "label", "confidence", "ts_ms"}
        if set(value) != required:
            missing = sorted(required - set(value))
            extra = sorted(set(value) - required)
            raise BridgeError(f"invalid detection fields missing={missing} extra={extra}")
        frame_id = value["frame_id"]
        label = value["label"]
        confidence = value["confidence"]
        ts_ms = value["ts_ms"]
        if isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0:
            raise BridgeError("frame_id must be a non-negative integer")
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise BridgeError("label must be null or a non-empty string")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise BridgeError("confidence must be numeric")
        if not 0.0 <= float(confidence) <= 1.0:
            raise BridgeError("confidence must be between 0 and 1")
        if isinstance(ts_ms, bool) or not isinstance(ts_ms, int) or ts_ms < 0:
            raise BridgeError("ts_ms must be a non-negative integer")
        return cls(frame_id, label.strip() if label is not None else None,
                   float(confidence), ts_ms)


@dataclass(frozen=True)
class StabilityConfig:
    min_confidence: float = 0.70
    consecutive_frames: int = 5
    release_after_ms: int = 1000


@dataclass(frozen=True)
class Timeouts:
    ack_s: float = 1.0
    running_s: float = 1.5
    idle_s: float = 3.5


@dataclass(frozen=True)
class Action:
    enabled: bool
    axis: str
    direction: str

    @property
    def command(self) -> str:
        return f"MOVE {self.axis} {self.direction}"

    @property
    def step_axis(self) -> int:
        return 1 if self.axis == "X" else 2


@dataclass(frozen=True)
class BridgeConfig:
    stability: StabilityConfig = field(default_factory=StabilityConfig)
    timeouts: Timeouts = field(default_factory=Timeouts)
    actions: Mapping[str, Action] = field(default_factory=dict)


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BridgeError(f"unknown {context} fields: {unknown}")


def load_config(path: str | Path) -> BridgeConfig:
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
    if (isinstance(stability_raw.get("min_confidence", 0.70), bool) or
            not isinstance(stability_raw.get("min_confidence", 0.70), (int, float))):
        raise BridgeError("min_confidence must be numeric")
    if (isinstance(stability_raw.get("consecutive_frames", 5), bool) or
            not isinstance(stability_raw.get("consecutive_frames", 5), int)):
        raise BridgeError("consecutive_frames must be an integer")
    if (isinstance(stability_raw.get("release_after_ms", 1000), bool) or
            not isinstance(stability_raw.get("release_after_ms", 1000), int)):
        raise BridgeError("release_after_ms must be an integer")
    stability = StabilityConfig(**stability_raw)
    if (not math.isfinite(stability.min_confidence) or
            not 0.0 <= stability.min_confidence <= 1.0):
        raise BridgeError("min_confidence must be between 0 and 1")
    if stability.consecutive_frames < 1:
        raise BridgeError("consecutive_frames must be at least 1")
    if stability.release_after_ms < 0:
        raise BridgeError("release_after_ms must be non-negative")

    timeouts_raw = raw.get("timeouts", {})
    if not isinstance(timeouts_raw, dict):
        raise BridgeError("timeouts must be an object")
    _reject_unknown(timeouts_raw, {"ack_s", "running_s", "idle_s"}, "timeouts")
    for name in ("ack_s", "running_s", "idle_s"):
        value = timeouts_raw.get(name, getattr(Timeouts(), name))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BridgeError(f"{name} must be numeric")
    timeouts = Timeouts(**timeouts_raw)
    timeout_values = (timeouts.ack_s, timeouts.running_s, timeouts.idle_s)
    if not all(math.isfinite(value) and value > 0 for value in timeout_values):
        raise BridgeError("all timeouts must be positive")

    actions_raw = raw.get("actions", {})
    if not isinstance(actions_raw, dict):
        raise BridgeError("actions must be an object")
    actions: dict[str, Action] = {}
    for label, action_raw in actions_raw.items():
        if not isinstance(label, str) or not label.strip():
            raise BridgeError("action label must be a non-empty string")
        if not isinstance(action_raw, dict):
            raise BridgeError(f"action {label!r} must be an object")
        _reject_unknown(action_raw, {"enabled", "axis", "direction"},
                        f"action {label!r}")
        if set(action_raw) != {"enabled", "axis", "direction"}:
            raise BridgeError(f"action {label!r} requires enabled, axis and direction")
        action = Action(**action_raw)
        if not isinstance(action.enabled, bool):
            raise BridgeError(f"action {label!r} enabled must be boolean")
        if action.axis not in {"X", "Y"}:
            raise BridgeError(f"action {label!r} axis must be X or Y")
        if action.direction not in {"DIR0", "DIR1"}:
            raise BridgeError(f"action {label!r} direction must be DIR0 or DIR1")
        actions[label] = action
    return BridgeConfig(stability, timeouts, actions)


class DetectionStabilizer:
    """Confirm consecutive detections and latch until a no-target interval."""

    def __init__(self, config: StabilityConfig):
        self.config = config
        self._candidate: Optional[str] = None
        self._count = 0
        self._latched = False
        self._absent_since_ms: Optional[int] = None
        self._last_frame_id: Optional[int] = None

    @property
    def latched(self) -> bool:
        return self._latched

    def offer(self, detection: Detection) -> Optional[str]:
        if self._last_frame_id is not None and detection.frame_id <= self._last_frame_id:
            self._candidate = None
            self._count = 0
            return None
        self._last_frame_id = detection.frame_id

        if self._latched:
            if detection.label is None:
                if self._absent_since_ms is None:
                    self._absent_since_ms = detection.ts_ms
                elif detection.ts_ms - self._absent_since_ms >= self.config.release_after_ms:
                    self._latched = False
                    self._absent_since_ms = None
                    self._candidate = None
                    self._count = 0
            else:
                self._absent_since_ms = None
            return None

        if detection.label is None or detection.confidence < self.config.min_confidence:
            self._candidate = None
            self._count = 0
            return None
        if detection.label == self._candidate:
            self._count += 1
        else:
            self._candidate = detection.label
            self._count = 1
        if self._count >= self.config.consecutive_frames:
            self._latched = True
            self._absent_since_ms = None
            return self._candidate
        return None


_INPUTS_RE = re.compile(
    r"^INPUTS RAW=([0-9A-Fa-f]{4}) STABLE=([0-9A-Fa-f]{4}) ACTIVE=([0-9A-Fa-f]{4})$")


def parse_inputs(line: str) -> Optional[int]:
    match = _INPUTS_RE.match(line)
    return int(match.group(3), 16) if match else None


def parse_status(line: str) -> Optional[dict[str, int]]:
    if not line.startswith("STATUS "):
        return None
    values: dict[str, int] = {}
    for token in line[7:].split():
        if "=" not in token:
            continue
        key, raw = token.split("=", 1)
        try:
            values[key] = int(raw, 10)
        except ValueError:
            return None
    required = {"ARMED", "MODE", "STEP_AXIS"}
    return values if required <= set(values) else None


def is_idle_status(status: Mapping[str, int]) -> bool:
    return (status.get("ARMED") == 0 and status.get("MODE") == 0 and
            status.get("STEP_AXIS") == 0 and status.get("SERVO_ARMED", 0) == 0 and
            status.get("SERVO_ACTIVE", 0) == 0)


class PySerialTransport:
    """Small pyserial adapter; imported lazily so dry-run needs no dependency."""

    def __init__(self, port: str, baudrate: int = 115200):
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise BridgeError("pyserial is required for real serial operation") from exc
        try:
            self._serial = serial.Serial(port=port, baudrate=baudrate, bytesize=8,
                                         parity="N", stopbits=1, timeout=0.1,
                                         write_timeout=0.5)
        except Exception as exc:
            raise BridgeError(f"cannot open serial port {port}: {exc}") from exc

    def write_line(self, line: str) -> None:
        self._serial.write((line + "\r\n").encode("ascii"))
        self._serial.flush()

    def read_line(self, deadline: float) -> Optional[str]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        self._serial.timeout = min(0.1, remaining)
        data = self._serial.readline()
        if not data:
            return None
        return data.decode("ascii", errors="replace").strip("\r\n")

    def close(self) -> None:
        self._serial.close()


class MotionController:
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

        self._read_until(idle, self.timeouts.ack_s, "idle STATUS", fatal=fatal)

    def _baseline_stop(self) -> None:
        self._expect_exact("STOP ALL", "OK STOP ALL")
        self._confirm_idle()

    def execute(self, action: Action) -> None:
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
            self._expect_exact("MOTION ARM", "OK MOTION ARMED 10S")
            self._expect_exact(action.command, "OK MOTION STARTING")

            def running(line: str) -> bool:
                status = parse_status(line)
                return (status is not None and status.get("MODE") == 3 and
                        status.get("STEP_AXIS") == action.step_axis)

            self._read_until(running, self.timeouts.running_s,
                             f"running axis {action.step_axis}")

            def idle(line: str) -> bool:
                status = parse_status(line)
                return status is not None and is_idle_status(status)

            self._read_until(idle, self.timeouts.idle_s, "motion completion")
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


def manual_detections(label: str, config: StabilityConfig) -> Iterable[Detection]:
    base_ms = int(time.monotonic() * 1000)
    for index in range(config.consecutive_frames):
        yield Detection(index, label, 1.0, base_ms + index * 100)


def run_events(events: Iterable[Detection], config: BridgeConfig, dry_run: bool,
               controller: Optional[MotionController],
               output: Callable[[str], None] = print) -> int:
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
            output(f"IGNORED disabled label={label} action={action.command}")
            continue
        if dry_run:
            output(f"DRY_RUN label={label} action={action.command}")
            continue
        if controller is None:
            raise BridgeError("motion controller is required")
        controller.execute(action)
    return 0


def jsonl_events(stream: Iterable[str]) -> Iterable[Detection]:
    for raw in stream:
        if raw.strip():
            yield Detection.from_json_line(raw)


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
    controller: Optional[MotionController] = None
    try:
        config = load_config(args.config)
        dry_run = args.dry_run or not args.allow_motion
        if args.allow_motion and args.dry_run:
            raise BridgeError("--allow-motion and --dry-run cannot be combined")
        if not dry_run:
            if not args.port:
                raise BridgeError("--port is required with --allow-motion")
            transport = PySerialTransport(args.port, args.baudrate)
            controller = MotionController(transport, config.timeouts,
                                          logger=lambda value: print(value,
                                                                     file=sys.stderr))
        events = (manual_detections(args.manual_label, config.stability)
                  if args.manual_label else jsonl_events(sys.stdin))
        return run_events(events, config, dry_run, controller)
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
