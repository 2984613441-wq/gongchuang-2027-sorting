"""Pure protocol types; no UART, GPIO, timing, or motion side effects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Device(IntEnum):
    MAIXCAM = 0x01
    RASPI = 0x02
    STM32 = 0x03


class Command(IntEnum):
    BARRIER_READY = 0x20
    MOTION_DONE = 0x22
    ITEM_RESULT = 0x23
    DISPLAY_ACK = 0x25


@dataclass(frozen=True, slots=True)
class Frame:
    """Already-delimited abstract frame.

    Binary outer-frame encoding is deliberately absent: its header and CRC-16
    rules are not frozen in protocol V0.4.
    """

    sender: Device
    receiver: Device
    task_id: int
    frame_seq: int
    command: Command
    payload: bytes


class DomainEvent:
    """Marker for events that may be consumed by the pure state machine."""


@dataclass(frozen=True, slots=True)
class DisplayAckMessage:
    """Direction-checked wire message without task-context conclusions."""

    task_id: int
    frame_seq: int
    target_seq: int
    render_result: int
    content_crc32: int


@dataclass(frozen=True, slots=True)
class DisplayAckReceived(DomainEvent):
    task_id: int
    frame_seq: int
    target_seq: int
    crc_match: bool
