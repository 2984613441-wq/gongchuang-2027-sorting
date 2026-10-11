"""Logical structured-vision ingest for the Raspberry Pi side.

This module models the data the Pi consumes from MaixCAM before any binary
wire encoding. BATCH_TARGETS and TARGET_REACQUIRE_RSP payloads are not frozen
in the interface contract, so this module deliberately stays at the logical
layer and never emits a serial frame.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from electrical_control.protocol import ItemTaskPayload, PayloadError


@dataclass(frozen=True)
class VisionTarget:
    target_seq: int
    class_id: int
    confidence: int = 0  # 0-100（BATCH_TARGETS 线置信度，去抖/排序依据）
    pixel_x: int = 0  # 中心点像素 X（去重/排序/复核定位，不进入运动）
    pixel_y: int = 0  # 中心点像素 Y
    box_id: int | None = None  # (color, shape) -> box_id 映射结果（未映射时 None）


@dataclass(frozen=True)
class BatchTargets:
    task_id: int
    targets: tuple[VisionTarget, ...]


# Frozen active class-id set (interface-contract §5.2): 1=cuboid absent this round.
ACTIVE_CLASS_IDS = frozenset({0, 2, 3, 4, 5, 6})

# ── BATCH_TARGETS 的 id 字节语义（2026-09-17 用户批准）────────────────
# True  = 校赛模式（当前）：该字节承载 box_id(1..6)，视觉侧把颜色折叠成货格号。
# False = 省赛/形状模式：该字节是形状 class_id。
#   🔴 2026-09-18 更正：这一支【当前不可用】，**不是**"换模式"，是"停摆"。
#      box_id 会被留成 None，而 socket_vision_source._expand() 对 None 一律拒识
#      → 切到 False 会让【每一件】都出不了货（独立复核于 2026-09-18 实测证实）。
#      省赛要真正可用，必须先补一条 class_id → box_id 的映射（颜色/形状联合判定），
#      只翻这个开关没用。原注释写"改成 False 即可（一行开关）"是**错的**，已删。
#      见 docs/交接台账-2026-09-17.md §2.1。
#
# 为什么必须这样做：线格式每目标只有 7 字节，**没有**独立 box_id 字段，
# 而 socket_vision_source.py 要求 box_id 是视觉真值（颜色折叠结果）；
# 它曾经拿 class_id 顶替 box_id，那是「颜色不进决策」——已知缺陷。
# 依据：docs/交接台账-2026-09-17.md §2.1；裁决材料
#       docs/design/2026-09-16-货物图片命名与image_id裁决.md
BATCH_ID_BYTE_IS_BOX_ID = True

_LOGGER = logging.getLogger(__name__)
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
        id_byte = data[offset]
        confidence = data[offset + 1]
        pixel_x = int.from_bytes(data[offset + 2 : offset + 4], "big")
        pixel_y = int.from_bytes(data[offset + 4 : offset + 6], "big")
        angle = data[offset + 6]

        # ── id 字节的语义（2026-09-17 用户批准，见
        #    docs/交接台账-2026-09-17.md §2.1）──────────────────────────
        # 线格式【没有】独立的 box_id 字段，也没有颜色字段；而
        # socket_vision_source.py 明确要求 box_id 必须是视觉真值
        # （颜色折叠结果），拿形状 class_id 当 box_id 就是「颜色不进决策」。
        # 所以校赛模式下，这个唯一的 id 字节直接承载 box_id(1..6)。
        # ⚠️ 省赛若要回到形状识别，【不是】把上面那个常量改成 False 就行 ——
        #    那一支会让 box_id 留 None → 上层 socket_vision_source 全部拒识
        #    → 一件都出不了货。必须先补 class_id → box_id 的映射。
        #    详见本文件顶部 :37-47 的说明。
        if BATCH_ID_BYTE_IS_BOX_ID:
            if not (1 <= id_byte <= 6):
                # 0（或其它越界值）= 视觉认不出这个件的颜色 → 只丢这一件，
                # 不能整帧抛错：否则同一帧里认得出来的件会被一起丢掉。
                # 上层 socket_vision_source 也会对 box_id=None 的件记 WARNING
                # 并继续，这里保持一致。
                _LOGGER.warning(
                    "id 字节 %d 不在 box_id 1..6（校赛模式）：拒识该件，其余照常",
                    id_byte,
                )
                continue
            class_id = id_byte
            box_id: int | None = id_byte
        else:
            class_id = id_byte
            box_id = None
            if class_id not in ACTIVE_CLASS_IDS:
                raise PayloadError(
                    f"class_id {class_id} not in frozen active set "
                    f"{sorted(ACTIVE_CLASS_IDS)}"
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
                box_id=box_id,
            )
        )
    return BatchTargets(task_id=task_id, targets=tuple(targets))


@dataclass(frozen=True)
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
                reason_lookup = getattr(
                    grasp_point_for_target, "rejection_reason_for_target", None
                )
                reason = (
                    reason_lookup(target)
                    if callable(reason_lookup)
                    else "抓取点回调返回 None，未提供细分原因"
                )
                _LOGGER.warning(
                    "拒识视觉目标: box_id=%r pixel=(%r,%r) reason=%s",
                    target.box_id, target.pixel_x, target.pixel_y, reason,
                )
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
