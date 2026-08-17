from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Direction(Enum):
    FORWARD = "forward"
    REVERSE = "reverse"


class DriverError(RuntimeError):
    """Base error reported by the host-side axis adapter."""


class DriverDisabledError(DriverError):
    pass


class DriverStoppedError(DriverError):
    pass


class MotionParametersNotConfigured(DriverError):
    pass


class PulsePortFault(DriverError):
    pass


@dataclass(frozen=True)
class MotionSegment:
    direction: Direction
    step_requests: int

    def __post_init__(self) -> None:
        if not isinstance(self.direction, Direction):
            raise MotionParametersNotConfigured("direction is not configured")
        if not isinstance(self.step_requests, int) or self.step_requests <= 0:
            raise MotionParametersNotConfigured(
                "a positive step request count must be supplied explicitly"
            )


@dataclass(frozen=True)
class AxisStatus:
    enabled: bool
    stopped: bool
    segment_active: bool
    requested_steps: int
    emitted_steps: int


class PulsePort(Protocol):
    def set_direction(self, direction: Direction) -> None: ...

    def request_step(self) -> None: ...

    def set_enabled(self, enabled: bool) -> None: ...

    def request_stop(self) -> None: ...


class AxisDriver(ABC):
    @abstractmethod
    def enable(self) -> None: ...

    @abstractmethod
    def disable(self) -> None: ...

    @abstractmethod
    def start_segment(self, segment: MotionSegment | None) -> None: ...

    @abstractmethod
    def emit_step(self) -> bool: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def poll(self) -> AxisStatus: ...


class StepDirAxisDriver(AxisDriver):
    """Hardware-neutral adapter that translates explicit intents to a pulse port."""

    def __init__(self, port: PulsePort) -> None:
        self._port = port
        self._enabled = False
        self._stopped = False
        self._fault: PulsePortFault | None = None
        self._segment: MotionSegment | None = None
        self._emitted_steps = 0

    def enable(self) -> None:
        if self._stopped:
            raise DriverStoppedError("stopped adapter cannot be re-enabled")
        if self._fault is not None:
            raise self._fault
        self._enabled = False
        self._segment = None
        try:
            self._port.set_enabled(True)
        except PulsePortFault as fault:
            self._fault = fault
            raise
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        self._segment = None
        self._port.set_enabled(False)

    def start_segment(self, segment: MotionSegment | None) -> None:
        self._require_operable()
        if segment is None:
            raise MotionParametersNotConfigured(
                "motion segment must be supplied explicitly"
            )
        self._segment = None
        try:
            self._port.set_direction(segment.direction)
        except PulsePortFault as fault:
            self._fault = fault
            raise
        self._segment = segment
        self._emitted_steps = 0

    def emit_step(self) -> bool:
        self._require_operable()
        if self._segment is None:
            raise MotionParametersNotConfigured("no motion segment is active")
        if self._emitted_steps >= self._segment.step_requests:
            return False
        try:
            self._port.request_step()
        except PulsePortFault as fault:
            self._fault = fault
            raise
        self._emitted_steps += 1
        return True

    def stop(self) -> None:
        self._stopped = True
        self._segment = None
        self._port.request_stop()

    def poll(self) -> AxisStatus:
        requested = self._segment.step_requests if self._segment else 0
        return AxisStatus(
            enabled=self._enabled,
            stopped=self._stopped,
            segment_active=self._segment is not None,
            requested_steps=requested,
            emitted_steps=self._emitted_steps,
        )

    def _require_operable(self) -> None:
        if self._fault is not None:
            raise self._fault
        if self._stopped:
            raise DriverStoppedError("axis adapter has been stopped")
        if not self._enabled:
            raise DriverDisabledError("axis adapter is disabled")
