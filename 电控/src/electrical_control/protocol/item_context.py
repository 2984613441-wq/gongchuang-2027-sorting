"""Protocol V0.4 item context shared by Raspberry Pi and STM32."""

from __future__ import annotations

from dataclasses import dataclass

from .display_ack import DisplayContent, _u8
from .errors import (
    ContractNotFrozen,
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


def encode_item_task_payload(item: ItemTaskPayload) -> bytes:
    """Refuse to guess coordinate/angle encoding that V0.4 has not frozen."""

    if not isinstance(item, ItemTaskPayload):
        raise TypeError("item must be ItemTaskPayload")
    raise ContractNotFrozen("ITEM_TASK coordinate and angle wire encoding is not frozen")


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
