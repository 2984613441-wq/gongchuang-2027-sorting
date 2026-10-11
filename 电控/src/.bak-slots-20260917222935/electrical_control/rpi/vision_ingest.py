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
# 返回 None = 该 box_id 在落点表里查不到 → 拒识该件（跳过），绝不猜点。
DropPointForBox = Callable[[int], "tuple[int, int] | None"]
# P3 (2026-09-16)：抓取点 = 该件的像素中心经"像素→装置 mm"换算后的结果。
# 返回 None = 该件没有可信的毫米抓取点 → 拒识该件（跳过），绝不回退成 (0,0)。
# 换算本身（相机标定 + 高度视差补偿）尚未实现，所以注入前不会有可发送的抓取点。
GraspPointForTarget = Callable[[VisionTarget], "tuple[int, int] | None"]


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
    grasp_point_for_target: GraspPointForTarget | None = None,
) -> tuple[ItemTaskPayload, ...]:
    """Map a vision batch to the Pi-side scheduling queue.

    The image id is supplied by the caller rather than guessed here. When
    ``drop_point_for_box`` is provided (the drop table has been measured and
    injected), each target's ``box_id`` resolves to a real drop point and the
    payload carries ``grip_angle=0xFF``. Without it, the drop fields stay
    logical placeholders (0) and the payload is deliberately not serializable
    (``grip_angle != 0xFF``).

    P3 (2026-09-16): the grasp point is a SECOND, independent input. It only
    exists once the pixel->mm calibration (plus the H-1 parallax compensation)
    has been measured and injected as ``grasp_point_for_target``. Without it
    ``pick_x_position/pick_y_position`` stay ``None``, so the payload cannot be
    serialized at all — P3 ships the transport channel, not the data source, and
    a fabricated (0,0) grasp point would be a deterministic empty claw (E-18).
    A target whose grasp point resolves to ``None`` is dropped, exactly like an
    unresolvable drop point: never fall back to a guessed coordinate.

    ``drop_point_for_box`` may return ``None`` for a box_id it cannot resolve
    (unknown box). Such a target is **dropped** — no payload, no queue entry, no
    ITEM_TASK — while the remaining targets still ship. A resolution failure
    must cost one item, never the whole chain (P11-A 设计 §1.3). Substituting a
    fallback point is never allowed: a guessed drop point is cargo in the wrong
    box.
    """

    if not isinstance(batch, BatchTargets):
        raise TypeError("batch must be a BatchTargets")
    if not callable(image_id_for_class):
        raise TypeError("image_id_for_class must be callable")
    if drop_point_for_box is not None and not callable(drop_point_for_box):
        raise TypeError("drop_point_for_box must be callable or None")
    if grasp_point_for_target is not None and not callable(grasp_point_for_target):
        raise TypeError("grasp_point_for_target must be callable or None")

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
            point = drop_point_for_box(target.box_id)
            if point is None:
                # 未知 box_id：拒识该件（不进队列、不发 ITEM_TASK），链路继续。
                continue
            x_position, y_position = point
            grip_angle = 0xFF  # frozen "no rotation" sentinel (interface-contract 5.2)

        pick_x_position: int | None = None
        pick_y_position: int | None = None
        if grasp_point_for_target is not None:
            grasp = grasp_point_for_target(target)
            if grasp is None:
                # 没有可信的毫米抓取点：拒识该件，绝不猜一个点（E-18）。
                continue
            pick_x_position, pick_y_position = grasp

        items.append(
            ItemTaskPayload(
                target_seq=target.target_seq,
                class_id=target.class_id,
                image_id=image_id_for_class(target.class_id),
                x_position=x_position,
                y_position=y_position,
                grip_angle=grip_angle,
                pick_x_position=pick_x_position,
                pick_y_position=pick_y_position,
            )
        )
    return tuple(items)


__all__ = [
    "BatchTargets",
    "DropPointForBox",
    "GraspPointForTarget",
    "FakeVisionSource",
    "ImageIdMap",
    "TargetReacquireResponse",
    "VisionTarget",
    "build_item_task_queue",
    "parse_batch_targets",
]
