"""Frozen command payload helpers layered on the unified outer-frame codec."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PayloadError
from .item_context import _ITEM_TASK_PAYLOAD_LEN
from .outer_frame import VERSION, OuterFrame, encode_outer_frame
from .types import Command, Device


def _u8(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFF:
        raise PayloadError(f"{name} must be an unsigned byte")
    return value


def _u32(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise PayloadError(f"{name} must be an unsigned 32-bit integer")
    return value


@dataclass(frozen=True)
class ItemResultPayload:
    target_seq: int
    result_code: int
    basis: int


def decode_item_result_payload(payload: bytes) -> ItemResultPayload:
    """Decode the frozen three-byte ITEM_RESULT payload."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise PayloadError("ITEM_RESULT payload must be bytes-like")
    payload = bytes(payload)
    if len(payload) != 3:
        raise PayloadError("ITEM_RESULT payload must be exactly 3 bytes")
    return ItemResultPayload(payload[0], payload[1], payload[2])


def encode_display_ack_frame(
    *,
    task_id: int,
    frame_seq: int,
    target_seq: int,
    render_result: int,
    content_crc32: int,
) -> bytes:
    """Build a full DISPLAY_ACK outer frame from its frozen six-byte payload."""

    payload = bytes(
        (
            _u8("target_seq", target_seq),
            _u8("render_result", render_result),
        )
    ) + _u32("content_crc32", content_crc32).to_bytes(4, "big")
    frame = OuterFrame(
        version=VERSION,
        sender=Device.RASPI,
        receiver=Device.STM32,
        task_id=task_id,
        frame_seq=frame_seq,
        command=int(Command.DISPLAY_ACK),
        payload=payload,
    )
    return encode_outer_frame(frame)


def encode_item_task_frame(
    *,
    task_id: int,
    frame_seq: int,
    payload: bytes,
) -> bytes:
    """Build an ITEM_TASK outer frame from a full, caller-supplied payload.

    The caller must provide the complete 12-byte payload (V0.9, P3 2026-09-16:
    drop point + grasp point; build it with ``encode_item_task_payload``); this
    helper does not guess the wire format.
    """

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise PayloadError("payload must be bytes-like")
    payload = bytes(payload)
    if len(payload) != _ITEM_TASK_PAYLOAD_LEN:
        raise PayloadError(f"ITEM_TASK payload must be exactly {_ITEM_TASK_PAYLOAD_LEN} bytes")
    frame = OuterFrame(
        version=VERSION,
        sender=Device.RASPI,
        receiver=Device.STM32,
        task_id=task_id,
        frame_seq=frame_seq,
        command=int(Command.ITEM_TASK),
        payload=payload,
    )
    return encode_outer_frame(frame)


__all__ = [
    "ItemResultPayload",
    "decode_item_result_payload",
    "encode_display_ack_frame",
    "encode_item_task_frame",
]
