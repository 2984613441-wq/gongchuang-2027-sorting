"""Frozen ACK(0x05) / NACK(0x06) reason codes and 2-byte payload decoding.

Frozen by user adjudication 2026-08-29 (docs/design/2026-08-29-ack-response-
definition-proposal.md, unresolved items E-1/E-2; mirrored from
electrical_control/stm32_logic/include/ec_protocol.h): payload is
reason(1) + target_seq(1) = 2 bytes. ACK reasons: ACCEPTED (ITEM_TASK
accepted), ACK_CONSUMED (DISPLAY_ACK consumed). NACK reasons: STALE_OR_ORDER /
UNEXPECTED_MESSAGE / SINGLE_TASK_ONLY / ACK_NOT_APPLICABLE / WRONG_ROUND /
TASK_REJECTED. target_seq echoes the item identity; 0xFF when unavailable.
"""

from __future__ import annotations

from .errors import PayloadError

ACK_REASONS: dict[int, str] = {
    0x00: "ACCEPTED",
    0x01: "ACK_CONSUMED",
}

NACK_REASONS: dict[int, str] = {
    0x10: "STALE_OR_ORDER",
    0x11: "UNEXPECTED_MESSAGE",
    0x12: "SINGLE_TASK_ONLY",
    0x13: "ACK_NOT_APPLICABLE",
    0x14: "WRONG_ROUND",
    0x15: "TASK_REJECTED",
}


def decode_ack_nack_payload(payload: bytes) -> tuple[int, int]:
    """Decode the frozen two-byte ACK/NACK payload into (reason_code, target_seq).

    Strictly validates the payload structure (bytes-like, exactly 2 bytes) and
    raises PayloadError on any violation. The reason code itself is deliberately
    NOT validated against the frozen tables: an as-yet-unfrozen reason must
    still surface as an observable event (e.g. ``UNKNOWN(0x16)``) so that
    integration debugging can see the raw code instead of a frame rejection.
    """

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise PayloadError("ACK/NACK payload must be bytes-like")
    payload = bytes(payload)
    if len(payload) != 2:
        raise PayloadError("ACK/NACK payload must be exactly 2 bytes")
    return payload[0], payload[1]


__all__ = ["ACK_REASONS", "NACK_REASONS", "decode_ack_nack_payload"]
