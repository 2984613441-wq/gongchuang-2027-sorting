"""Frozen DISPLAY_ACK payload and display-content digest rules."""

from __future__ import annotations

from dataclasses import dataclass
import zlib

from .errors import PayloadError
from .types import DisplayAckMessage, DisplayAckReceived


def _u8(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFF:
        raise PayloadError(f"{name} must be an unsigned byte")
    return value


def crc32_iso_hdlc(data: bytes) -> int:
    """Return CRC-32/ISO-HDLC as an unsigned integer."""

    return zlib.crc32(bytes(data)) & 0xFFFFFFFF


@dataclass(frozen=True)
class DisplayContent:
    target_seq: int
    class_id: int
    image_id: int
    success_count: int
    result_code: int

    def canonical_bytes(self) -> bytes:
        return bytes(
            (
                _u8("target_seq", self.target_seq),
                _u8("class_id", self.class_id),
                _u8("image_id", self.image_id),
                _u8("success_count", self.success_count),
                _u8("result_code", self.result_code),
            )
        )

    @property
    def crc32(self) -> int:
        return crc32_iso_hdlc(self.canonical_bytes())


@dataclass(frozen=True)
class DisplayAckPayload:
    target_seq: int
    render_result: int
    content_crc32: int


def encode_display_ack_payload(content: DisplayContent, render_result: int) -> bytes:
    target_seq = _u8("target_seq", content.target_seq)
    result = _u8("render_result", render_result)
    return bytes((target_seq, result)) + content.crc32.to_bytes(4, "big")


def _parse_display_ack_payload(payload: bytes) -> DisplayAckPayload:
    if len(payload) != 6:
        raise PayloadError("DISPLAY_ACK payload must be exactly 6 bytes")
    return DisplayAckPayload(
        target_seq=payload[0],
        render_result=payload[1],
        content_crc32=int.from_bytes(payload[2:6], "big"),
    )


def decode_display_ack_payload(
    payload: bytes,
    *,
    expected_content: DisplayContent,
) -> DisplayAckPayload:
    parsed = _parse_display_ack_payload(bytes(payload))
    if parsed.render_result != 0x00:
        raise PayloadError("DISPLAY_ACK is not RENDERED")
    if parsed.target_seq != expected_content.target_seq:
        raise PayloadError("DISPLAY_ACK target does not match active item")
    if parsed.content_crc32 != expected_content.crc32:
        raise PayloadError("DISPLAY_ACK content CRC32 does not match active item")
    return parsed


class DisplayAckContextValidator:
    """Apply active-item context after stateless wire validation."""

    def to_domain_event(
        self,
        message: DisplayAckMessage,
        *,
        expected_display_content: DisplayContent,
    ) -> DisplayAckReceived:
        if message.render_result != 0x00:
            raise PayloadError("DISPLAY_ACK is not RENDERED")
        if message.target_seq != expected_display_content.target_seq:
            raise PayloadError("DISPLAY_ACK target does not match active item")
        if message.content_crc32 != expected_display_content.crc32:
            raise PayloadError("DISPLAY_ACK content CRC32 does not match active item")
        return DisplayAckReceived(
            task_id=message.task_id,
            frame_seq=message.frame_seq,
            target_seq=message.target_seq,
            crc_match=True,
        )


parse_display_ack_payload = _parse_display_ack_payload
