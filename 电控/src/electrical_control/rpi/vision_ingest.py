"""Logical structured-vision ingest for the Raspberry Pi side.

This module models the data the Pi consumes from MaixCAM before any binary
wire encoding. BATCH_TARGETS and TARGET_REACQUIRE_RSP payloads are not frozen
in the interface contract, so this module deliberately stays at the logical
layer and never emits a serial frame.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from electrical_control.protocol import ItemTaskPayload, PayloadError


@dataclass(frozen=True, slots=True)
class VisionTarget:
    target_seq: int
    class_id: int
    confidence: int = 0  # 0-100（BATCH_TARGETS 线置信度，去抖/排序依据）
    pixel_x: int = 0  # 中心点像素 X（去重/排序/复核定位，不进入运动）
    pixel_y: int = 0  # 中心点像素 Y
    box_id: int | None = None  # (color, shape) -> box_id 映射结果（未映射时 None）


@dataclass(frozen=True, slots=True)
class BatchTargets:
    task_id: int
    targets: tuple[VisionTarget, ...]


# Frozen active class-id set (interface-contract §5.2): 1=cuboid absent this round.
ACTIVE_CLASS_IDS = frozenset({0, 2, 3, 4, 5, 6})
# BATCH_TARGETS per-target wire size (interface-contract §5.1, frozen 2026-09-01).
_BATCH_TARGET_BYTES = 7
_BATCH_ANGLE_NONE = 0xFF


def parse_batch_targets(data: bytes) -> BatchTargets:
    """Parse a frozen BATCH_TARGETS data region (big-endian 7 bytes/target).

    Layout (interface-contract §5.1):
        target_count(1) + task_id(2, BE) + target[N]
    Each target:
        class_id(1) + confidence(1, 0-100) + X(2, BE) + Y(2, BE) + angle(1, 0xFF)

    X/Y are center pixel coordinates — not calibrated, used only for
    dedup/sort/reacquire localization and never fed into motion. The
    ``angle`` byte must be ``0xFF`` (claw does not rotate).
    """

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise PayloadError("BATCH_TARGETS data must be bytes-like")
    data = bytes(data)
    if len(data) < 3:
        raise PayloadError("BATCH_TARGETS data is shorter than its 3-byte header")
    target_count = data[0]
    task_id = int.from_bytes(data[1:3], "big")
    expected = 3 + target_count * _BATCH_TARGET_BYTES
    if len(data) != expected:
        raise PayloadError(
            f"BATCH_TARGETS data length {len(data)} != expected {expected} "
            f"for {target_count} target(s)"
        )

    targets: list[VisionTarget] = []
    for index in range(target_count):
        offset = 3 + index * _BATCH_TARGET_BYTES
        class_id = data[offset]
        confidence = data[offset + 1]
        pixel_x = int.from_bytes(data[offset + 2 : offset + 4], "big")
        pixel_y = int.from_bytes(data[offset + 4 : offset + 6], "big")
        angle = data[offset + 6]

        if class_id not in ACTIVE_CLASS_IDS:
            raise PayloadError(
                f"class_id {class_id} not in frozen active set {sorted(ACTIVE_CLASS_IDS)}"
            )
        if confidence > 100:
            raise PayloadError(f"confidence {confidence} out of range (0-100)")
        if angle != _BATCH_ANGLE_NONE:
            raise PayloadError("grip angle must be 0xFF (claw does not rotate)")
        targets.append(
            VisionTarget(
                target_seq=index + 1,
                class_id=class_id,
                confidence=confidence,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
            )
        )
    return BatchTargets(task_id=task_id, targets=tuple(targets))


@dataclass(frozen=True, slots=True)
class TargetReacquireResponse:
    task_id: int
    target_seq: int
    accepted: bool
    class_id: int | None = None


ImageIdMap = Callable[[int], int]  # deprecated: image_id is frozen to equal class_id
DropPointForBox = Callable[[int], tuple[int, int]]


class FakeVisionSource:
    """Deterministic, gate-controlled source of logical vision batches."""

    def __init__(self, batches: Iterable[BatchTargets]) -> None:
        self._batches = iter(tuple(batches))
        self._permitted = False

    def set_permitted(self, permitted: bool) -> None:
        self._permitted = permitted

    def next_if_permitted(self) -> BatchTargets | None:
        if not self._permitted:
            return None
        return next(self._batches, None)


def build_item_task_queue(
    batch: BatchTargets,
    *,
    image_id_for_class: ImageIdMap,
    drop_point_for_box: DropPointForBox | None = None,
) -> tuple[ItemTaskPayload, ...]:
    """Map a vision batch to the Pi-side scheduling queue.

    The image id is supplied by the caller rather than guessed here. When
    ``drop_point_for_box`` is provided (the drop table has been measured and
    injected), each target's ``box_id`` resolves to a real drop point and the
    payload carries ``grip_angle=0xFF`` so it becomes serializable. Without it,
    the coordinate fields stay logical placeholders (0) and the payload is
    deliberately not serializable (``grip_angle != 0xFF``) — the wire-boundary
    check in ``encode_item_task_payload`` enforces that fail-closed behavior.
    """

    if not isinstance(batch, BatchTargets):
        raise TypeError("batch must be a BatchTargets")
    if not callable(image_id_for_class):
        raise TypeError("image_id_for_class must be callable")
    if drop_point_for_box is not None and not callable(drop_point_for_box):
        raise TypeError("drop_point_for_box must be callable or None")

    items: list[ItemTaskPayload] = []
    for target in batch.targets:
        if not isinstance(target, VisionTarget):
            raise TypeError("batch targets must be VisionTarget instances")
        x_position = y_position = 0
        grip_angle = 0  # placeholder: not serializable until drop table lands
        if drop_point_for_box is not None:
            if target.box_id is None:
                raise TypeError(
                    "drop_point_for_box requires every VisionTarget to carry a box_id"
                )
            x_position, y_position = drop_point_for_box(target.box_id)
            grip_angle = 0xFF  # frozen "no rotation" sentinel (interface-contract 5.2)
        items.append(
            ItemTaskPayload(
                target_seq=target.target_seq,
                class_id=target.class_id,
                image_id=image_id_for_class(target.class_id),
                x_position=x_position,
                y_position=y_position,
                grip_angle=grip_angle,
            )
        )
    return tuple(items)


__all__ = [
    "BatchTargets",
    "DropPointForBox",
    "FakeVisionSource",
    "ImageIdMap",
    "TargetReacquireResponse",
    "VisionTarget",
    "build_item_task_queue",
    "parse_batch_targets",
]
