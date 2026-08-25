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
) -> tuple[ItemTaskPayload, ...]:
    """Map a vision batch to the Pi-side scheduling queue.

    The image id is supplied by the caller rather than guessed here. Coordinate
    fields are logical placeholders (0) because the drop-table physical
    quantities have not been supplied yet; ``encode_item_task_payload`` still
    refuses to serialize the placeholder (grip_angle is not 0xFF).
    """

    if not isinstance(batch, BatchTargets):
        raise TypeError("batch must be a BatchTargets")
    if not callable(image_id_for_class):
        raise TypeError("image_id_for_class must be callable")

    items: list[ItemTaskPayload] = []
    for target in batch.targets:
        if not isinstance(target, VisionTarget):
            raise TypeError("batch targets must be VisionTarget instances")
        items.append(
            ItemTaskPayload(
                target_seq=target.target_seq,
                class_id=target.class_id,
                image_id=image_id_for_class(target.class_id),
                x_position=0,
                y_position=0,
                grip_angle=0,
            )
        )
    return tuple(items)


__all__ = [
    "BatchTargets",
    "FakeVisionSource",
    "ImageIdMap",
    "TargetReacquireResponse",
    "VisionTarget",
    "build_item_task_queue",
]
