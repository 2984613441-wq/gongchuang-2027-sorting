"""Pure protocol types; no UART, GPIO, timing, or motion side effects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Device(IntEnum):
    MAIXCAM = 0x01
    RASPI = 0x02
    STM32 = 0x03


class Command(IntEnum):
    HEARTBEAT = 0x01
    HEARTBEAT_ACK = 0x02
    DEVICE_READY = 0x03
    ERROR = 0x04
    ACK = 0x05
    NACK = 0x06
    BATCH_TARGETS = 0x10
    TARGET_REACQUIRE_REQ = 0x11
    TARGET_REACQUIRE_RSP = 0x12
    DIAG_SCAN = 0x13
    BARRIER_READY = 0x20
    ITEM_TASK = 0x21
    MOTION_DONE = 0x22
    ITEM_RESULT = 0x23
    DISPLAY_DATA = 0x24
    DISPLAY_ACK = 0x25
    ESTOP = 0x26


@dataclass(frozen=True)
class Frame:
    """Already-delimited abstract frame.

    Binary outer-frame encoding is deliberately absent here (callers supply
    already-delimited frames). The outer frame is frozen in protocol V0.5:
    header 0xA5 0x5A, version 0x01, CRC-16/MODBUS, big-endian multi-byte fields.
    """

    sender: Device
    receiver: Device
    task_id: int
    frame_seq: int
    command: Command
    payload: bytes


class DomainEvent:
    """Marker for events that may be consumed by the pure state machine."""


@dataclass(frozen=True)
class DisplayAckMessage:
    """Direction-checked wire message without task-context conclusions."""

    task_id: int
    frame_seq: int
    target_seq: int
    render_result: int
    content_crc32: int


@dataclass(frozen=True)
class DisplayAckReceived(DomainEvent):
    task_id: int
    frame_seq: int
    target_seq: int
    crc_match: bool
