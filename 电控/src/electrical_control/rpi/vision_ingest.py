"""Logical structured-vision ingest for the Raspberry Pi side.

This module models the data the Pi consumes from MaixCAM before any binary
wire encoding. BATCH_TARGETS and TARGET_REACQUIRE_RSP payloads are not frozen
in the interface contract, so this module deliberately stays at the logical
layer and never emits a serial frame.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from electrical_control.protocol import ItemTaskPayload


@dataclass(frozen=True, slots=True)
class VisionTarget:
    target_seq: int
    class_id: int
    box_id: int | None = None


@dataclass(frozen=True, slots=True)
class BatchTargets:
    task_id: int
    targets: tuple[VisionTarget, ...]


@dataclass(frozen=True, slots=True)
class TargetReacquireResponse:
    task_id: int
    target_seq: int
    accepted: bool
    class_id: int | None = None


ImageIdMap = Callable[[int], int]
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
]
