"""Bounded, structured, host-side logging for the Raspberry Pi scheduler.

No serial, display, or video data is stored here. Callers supply monotonic
timestamps; this module owns no clock and makes no hardware assumptions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite


STARTUP = "startup"
TASK = "task"
RESULT = "result"
DISPLAY = "display"
FAULT = "fault"
STAGE = "stage"

LOG_KINDS = frozenset({STARTUP, TASK, RESULT, DISPLAY, FAULT, STAGE})


@dataclass(frozen=True)
class LogEntry:
    kind: str
    now: float
    round_id: str | None = None
    task_id: int | None = None
    frame_seq: int | None = None
    target_seq: int | None = None
    result_code: int | None = None
    success_count: int | None = None
    detail: str | None = None


class CentralLog:
    """Fixed-capacity in-memory log; oldest entries are dropped when full."""

    def __init__(self, capacity: int) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("log capacity must be an explicit positive integer")
        self._capacity = capacity
        self._entries: deque[LogEntry] = deque()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def entries(self) -> tuple[LogEntry, ...]:
        return tuple(self._entries)

    @property
    def last(self) -> LogEntry | None:
        return self._entries[-1] if self._entries else None

    def record(
        self,
        kind: str,
        *,
        now: float,
        round_id: str | None = None,
        task_id: int | None = None,
        frame_seq: int | None = None,
        target_seq: int | None = None,
        result_code: int | None = None,
        success_count: int | None = None,
        detail: str | None = None,
    ) -> LogEntry:
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind!r}")
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not isfinite(now):
            raise ValueError("now must be a finite number")
        entry = LogEntry(
            kind=kind,
            now=float(now),
            round_id=round_id,
            task_id=task_id,
            frame_seq=frame_seq,
            target_seq=target_seq,
            result_code=result_code,
            success_count=success_count,
            detail=detail,
        )
        self._entries.append(entry)
        while len(self._entries) > self._capacity:
            self._entries.popleft()
        return entry


__all__ = [
    "DISPLAY",
    "FAULT",
    "LOG_KINDS",
    "RESULT",
    "STAGE",
    "STARTUP",
    "TASK",
    "CentralLog",
    "LogEntry",
]
