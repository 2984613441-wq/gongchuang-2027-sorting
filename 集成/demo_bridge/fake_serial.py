"""Deterministic line-oriented fake serial transport for bridge tests."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Iterable, Optional


class FakeSerial:
    def __init__(self, responder: Callable[[str], Iterable[str]]):
        self.responder = responder
        self.sent: list[str] = []
        self._received: deque[str] = deque()
        self.closed = False

    def write_line(self, line: str) -> None:
        if self.closed:
            raise OSError("fake serial is closed")
        self.sent.append(line)
        self._received.extend(self.responder(line))

    def read_line(self, deadline: float) -> Optional[str]:
        if self.closed:
            raise OSError("fake serial is closed")
        if self._received:
            return self._received.popleft()
        if time.monotonic() < deadline:
            time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))
        return None

    def queue(self, *lines: str) -> None:
        self._received.extend(lines)

    def close(self) -> None:
        self.closed = True

