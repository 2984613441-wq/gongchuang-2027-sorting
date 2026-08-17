from __future__ import annotations

from .axis import Direction


class FakePulsePort:
    """Records abstract output requests; it cannot cause physical movement."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object | None]] = []
        self._pending_faults: dict[str, BaseException] = {}

    @property
    def step_count(self) -> int:
        return sum(event == "STEP" for event, _ in self.events)

    def fail_next(self, operation: str, fault: BaseException) -> None:
        self._pending_faults[operation] = fault

    def set_direction(self, direction: Direction) -> None:
        self._record("DIR", direction)

    def request_step(self) -> None:
        self._record("STEP", None)

    def set_enabled(self, enabled: bool) -> None:
        self._record("ENABLE", enabled)

    def request_stop(self) -> None:
        self._record("STOP", None)

    def _record(self, operation: str, value: object | None) -> None:
        fault = self._pending_faults.pop(operation, None)
        if fault is not None:
            raise fault
        self.events.append((operation, value))
