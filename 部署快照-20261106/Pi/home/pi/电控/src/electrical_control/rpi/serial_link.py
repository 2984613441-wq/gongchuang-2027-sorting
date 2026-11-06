"""Host-only serial link abstraction for the Raspberry Pi outbound path.

SerialLink is a structural Protocol: one complete outer frame per send/receive,
never exposing wire details (baud rate, port, framing). FakeSerialLink records
outbound frames for assertions and serves a deterministic inbound queue for
host-side tests. Production transport (such as pyserial) is injected by
deployment configuration; no port or baud rate is hard-coded here.
"""

from __future__ import annotations

from collections import deque
from typing import Protocol


class SerialLink(Protocol):
    """One complete outer frame per send/receive; never exposes wire details."""

    def send(self, frame: bytes) -> None: ...

    def receive(self) -> bytes | None: ...  # None = nothing buffered yet


class FakeSerialLink:
    """Records outbound frames; deterministic inbound queue for host tests."""

    def __init__(self) -> None:
        self._sent: list[bytes] = []
        self._inbound: deque[bytes] = deque()

    @property
    def sent(self) -> tuple[bytes, ...]:
        """All frames sent so far, in order."""
        return tuple(self._sent)

    def queue_inbound(self, frame: bytes) -> None:
        """Append one inbound frame for a future receive() call (for tests)."""
        self._inbound.append(bytes(frame))

    def send(self, frame: bytes) -> None:
        self._sent.append(bytes(frame))

    def receive(self) -> bytes | None:
        """Return the oldest queued inbound frame, or None when empty."""
        if not self._inbound:
            return None
        return self._inbound.popleft()


__all__ = ["SerialLink", "FakeSerialLink"]
