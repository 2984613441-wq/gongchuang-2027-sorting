"""Protocol V0.4 item context shared by Raspberry Pi and STM32."""

from __future__ import annotations

from dataclasses import dataclass

from .display_ack import DisplayContent, _u8
from .errors import (
    PayloadError,
    ProtocolError,
    ResultIdentityConflict,
    SuccessCountOverflow,
)


@dataclass(frozen=True, slots=True)
class ItemTaskPayload:
    """Frozen logical ITEM_TASK fields; wire encoding remains incomplete."""

    target_seq: int
    class_id: int
    image_id: int
    x_position: int
    y_position: int
    grip_angle: int

    def __post_init__(self) -> None:
        _u8("target_seq", self.target_seq)
        _u8("class_id", self.class_id)
        _u8("image_id", self.image_id)

    @property
    def identity_prefix(self) -> bytes:
        return encode_item_task_identity_prefix(
            self.target_seq, self.class_id, self.image_id
        )


@dataclass(frozen=True, slots=True)
class ItemTaskIdentity:
    """Frozen ITEM_TASK identity prefix; X/Y/angle are not included here."""

    target_seq: int
    class_id: int
    image_id: int

    def __post_init__(self) -> None:
        _u8("target_seq", self.target_seq)
        _u8("class_id", self.class_id)
        _u8("image_id", self.image_id)

    @property
    def prefix(self) -> bytes:
        return bytes((self.target_seq, self.class_id, self.image_id))


def encode_item_task_identity_prefix(
    target_seq: int, class_id: int, image_id: int
) -> bytes:
    """Encode only the three frozen identity bytes of an ITEM_TASK payload."""

    return ItemTaskIdentity(target_seq, class_id, image_id).prefix


def decode_item_task_identity_prefix(payload: bytes) -> tuple[ItemTaskIdentity, bytes]:
    """Decode the frozen identity prefix and return the opaque remainder."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise PayloadError("ITEM_TASK payload must be bytes-like")
    payload = bytes(payload)
    if len(payload) < 3:
        raise PayloadError("ITEM_TASK payload is shorter than its identity prefix")
    identity = ItemTaskIdentity(payload[0], payload[1], payload[2])
    return identity, payload[3:]


# Frozen ITEM_TASK wire constraints (interface-contract sec. 5.2): X/Y origin
# = device center, units 0.1 mm, |value| > 1450 (+-145.0 mm) is out of range;
# grip_angle is always 0xFF (claw does not rotate; 0..180 unused this round).
_ITEM_TASK_X_LIMIT = 1450
_ITEM_TASK_ANGLE_NONE = 0xFF


def _coord(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PayloadError(f"{name} must be a signed integer")
    if not -_ITEM_TASK_X_LIMIT <= value <= _ITEM_TASK_X_LIMIT:
        raise PayloadError(f"{name} out of range (+-{_ITEM_TASK_X_LIMIT})")
    return value


def encode_item_task_payload(item: ItemTaskPayload) -> bytes:
    """Encode the frozen 8-byte ITEM_TASK payload (interface-contract sec. 5.2).

    Coordinate/angle validity is enforced here at the wire boundary, not in
    ``ItemTaskPayload.__post_init__``: the payload class stays a loose logical
    carrier (placeholder 0/0/0 is a valid intermediate state until the drop
    table lands)."""

    if not isinstance(item, ItemTaskPayload):
        raise TypeError("item must be ItemTaskPayload")
    x = _coord("x_position", item.x_position)
    y = _coord("y_position", item.y_position)
    _u8("grip_angle", item.grip_angle)
    if item.grip_angle != _ITEM_TASK_ANGLE_NONE:
        raise PayloadError("grip_angle must be 0xFF (claw does not rotate)")
    if item.image_id != item.class_id:
        raise PayloadError("image_id must equal class_id (frozen 1:1 invariant)")
    if not 1 <= item.target_seq <= 255:
        raise PayloadError("target_seq must be within [1, 255]")
    return (
        bytes((item.target_seq, item.class_id, item.image_id))
        + x.to_bytes(2, "big", signed=True)
        + y.to_bytes(2, "big", signed=True)
        + bytes((item.grip_angle,))
    )


def decode_item_task_payload(payload: bytes) -> ItemTaskPayload:
    """Decode the frozen 8-byte ITEM_TASK payload, rejecting any violation."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise PayloadError("ITEM_TASK payload must be bytes-like")
    payload = bytes(payload)
    if len(payload) != 8:
        raise PayloadError("ITEM_TASK payload must be exactly 8 bytes")
    if payload[7] != _ITEM_TASK_ANGLE_NONE:
        raise PayloadError("grip_angle must be 0xFF (claw does not rotate)")
    x = int.from_bytes(payload[3:5], "big", signed=True)
    y = int.from_bytes(payload[5:7], "big", signed=True)
    if not -_ITEM_TASK_X_LIMIT <= x <= _ITEM_TASK_X_LIMIT:
        raise PayloadError(f"x_position out of range (+-{_ITEM_TASK_X_LIMIT})")
    if not -_ITEM_TASK_X_LIMIT <= y <= _ITEM_TASK_X_LIMIT:
        raise PayloadError(f"y_position out of range (+-{_ITEM_TASK_X_LIMIT})")
    if payload[2] != payload[1]:
        raise PayloadError("image_id must equal class_id (frozen 1:1 invariant)")
    return ItemTaskPayload(
        target_seq=payload[0],
        class_id=payload[1],
        image_id=payload[2],
        x_position=x,
        y_position=y,
        grip_angle=payload[7],
    )


class RoundSuccessCounter:
    """One-byte per-round counter with identical deterministic node behavior."""

    SUCCESS = 0x00

    def __init__(self, *, initial_value: int = 0) -> None:
        self._value = _u8("initial_value", initial_value)
        self._recorded_results: dict[tuple[int, int], int] = {}

    @property
    def value(self) -> int:
        return self._value

    @property
    def can_accept_new_item(self) -> bool:
        return self._value < 0xFF

    def record_item_result(
        self,
        *,
        result_code: int,
        task_id: int | None = None,
        frame_seq: int | None = None,
    ) -> bool:
        code = _u8("result_code", result_code)
        if task_id is None or frame_seq is None:
            raise ProtocolError("result counting requires task_id and frame_seq")
        identity = (task_id, frame_seq)
        if identity in self._recorded_results:
            if self._recorded_results[identity] != code:
                raise ResultIdentityConflict(
                    "same result identity has conflicting result codes"
                )
            return False
        if code != self.SUCCESS:
            self._recorded_results[identity] = code
            return True
        if self._value == 0xFF:
            raise SuccessCountOverflow("round success count cannot exceed 255")
        self._value += 1
        self._recorded_results[identity] = code
        return True

    def reset_round(self, *, new_round_verified: bool) -> None:
        if not new_round_verified:
            raise ProtocolError("success count reset requires a verified new round")
        self._value = 0
        self._recorded_results.clear()


def build_display_content(
    *,
    item_task: ItemTaskPayload,
    success_count: int,
    result_code: int,
) -> DisplayContent:
    return DisplayContent(
        target_seq=item_task.target_seq,
        class_id=item_task.class_id,
        image_id=item_task.image_id,
        success_count=_u8("success_count", success_count),
        result_code=_u8("result_code", result_code),
    )


def verify_counter_context(
    *,
    local_task_id: int,
    local_success_count: int,
    local_item: tuple[int, int, int, int],
    peer_task_id: int,
    peer_success_count: int,
    peer_item: tuple[int, int, int, int],
) -> None:
    if (
        local_task_id != peer_task_id
        or local_success_count != peer_success_count
        or local_item != peer_item
    ):
        raise ProtocolError("round success counter context is not synchronized")
