"""Unified binary outer-frame codec for protocol V0.5.

This module implements the frozen outer-frame subset shared by MaixCAM,
Raspberry Pi, and STM32:

  header 0xA5 0x5A
  version 0x01
  sender / receiver device ids
  task_id / frame_seq / data_len big-endian
  frame CRC = CRC-16/MODBUS (poly 0x8005, init 0xFFFF, no reflect, no final xor)

The frame is intentionally device-agnostic. Command-specific payload parsing
stays in the higher-level codecs; ITEM_TASK X/Y/angle encoding and timeouts are
not frozen and must not be guessed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PayloadError
from .types import Device


HEADER_0 = 0xA5
HEADER_1 = 0x5A
VERSION = 0x01

HEADER_LEN = 12
CRC_LEN = 2
FRAME_OVERHEAD = HEADER_LEN + CRC_LEN

_DEVICE_IDS = frozenset(int(device) for device in Device)


def _u8(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFF:
        raise PayloadError(f"{name} must be an unsigned byte")
    return value


def _u16(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFF:
        raise PayloadError(f"{name} must be an unsigned 16-bit integer")
    return value


def _device(name: str, value: Device | int) -> int:
    if isinstance(value, Device):
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value in _DEVICE_IDS:
        return value
    raise PayloadError(f"{name} must be a known device id")


def _device_from_byte(name: str, value: int) -> Device:
    if value not in _DEVICE_IDS:
        raise PayloadError(f"{name} has an unknown device id 0x{value:02X}")
    return Device(value)


def crc16_modbus(data: bytes) -> int:
    """Return CRC-16/MODBUS as an unsigned integer.

    Golden vector: b"123456789" -> 0x4B37.
    """

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    crc = 0xFFFF
    for byte in bytes(data):
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


@dataclass(frozen=True)
class OuterFrame:
    version: int
    sender: Device
    receiver: Device
    task_id: int
    frame_seq: int
    command: int
    payload: bytes

    def __post_init__(self) -> None:
        _u8("version", self.version)
        _device("sender", self.sender)
        _device("receiver", self.receiver)
        _u16("task_id", self.task_id)
        _u16("frame_seq", self.frame_seq)
        _u8("command", self.command)
        if not isinstance(self.payload, bytes):
            raise PayloadError("payload must be bytes")


def encode_outer_frame(frame: OuterFrame) -> bytes:
    """Serialize an OuterFrame into the frozen binary outer-frame format."""

    if not isinstance(frame, OuterFrame):
        raise TypeError("frame must be an OuterFrame")
    if frame.version != VERSION:
        raise PayloadError("protocol version must be 0x01")

    body = bytes(
        (
            HEADER_0,
            HEADER_1,
            frame.version,
            _device("sender", frame.sender),
            _device("receiver", frame.receiver),
            (frame.task_id >> 8) & 0xFF,
            frame.task_id & 0xFF,
            (frame.frame_seq >> 8) & 0xFF,
            frame.frame_seq & 0xFF,
            frame.command,
            (len(frame.payload) >> 8) & 0xFF,
            len(frame.payload) & 0xFF,
        )
    )
    crc = crc16_modbus(body + frame.payload)
    return body + frame.payload + crc.to_bytes(2, "big")


def decode_outer_frame(data: bytes) -> OuterFrame:
    """Parse one complete frame and validate header, version, and CRC.

    Trailing bytes beyond the declared frame length are ignored, matching the
    C implementation, which decodes from a frame boundary.
    """

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise PayloadError("frame data must be bytes-like")
    data = bytes(data)
    if len(data) < FRAME_OVERHEAD:
        raise PayloadError("frame is shorter than the outer-frame overhead")
    if data[0] != HEADER_0 or data[1] != HEADER_1:
        raise PayloadError("frame header does not match 0xA5 0x5A")
    if data[2] != VERSION:
        raise PayloadError("protocol version is not 0x01")

    data_len = int.from_bytes(data[10:12], "big")
    crc_offset = HEADER_LEN + data_len
    total = crc_offset + CRC_LEN
    if len(data) < total:
        raise PayloadError("frame is shorter than its declared data length")

    expected_crc = crc16_modbus(data[:crc_offset])
    actual_crc = int.from_bytes(data[crc_offset:total], "big")
    if actual_crc != expected_crc:
        raise PayloadError("frame CRC does not match")

    return OuterFrame(
        version=data[2],
        sender=_device_from_byte("sender", data[3]),
        receiver=_device_from_byte("receiver", data[4]),
        task_id=int.from_bytes(data[5:7], "big"),
        frame_seq=int.from_bytes(data[7:9], "big"),
        command=data[9],
        payload=data[HEADER_LEN:crc_offset],
    )


__all__ = [
    "FRAME_OVERHEAD",
    "HEADER_0",
    "HEADER_1",
    "HEADER_LEN",
    "CRC_LEN",
    "OuterFrame",
    "VERSION",
    "crc16_modbus",
    "decode_outer_frame",
    "encode_outer_frame",
]
