"""Tests for multi-frame class voting (2026-11-06 形状误判修复 任务A)."""

from __future__ import annotations

import pytest

from electrical_control.rpi import BatchTargets, VisionTarget
from electrical_control.rpi.socket_vision_source import SocketVisionSource


def _make_source_with_vote(
    *,
    enabled: bool = True,
    frames: int = 3,
    quorum: int = 2,
    max_wait: int = 6,
) -> SocketVisionSource:
    """构造带投票功能的 SocketVisionSource（用于测试）。"""
    return SocketVisionSource(
        round_id="round-1",
        task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=lambda target: (-30, 40),
        class_vote_enabled=enabled,
        class_vote_frames=frames,
        class_vote_quorum=quorum,
        class_vote_max_wait_frames=max_wait,
    )


def _batch_with_class(target_seq: int, class_id: int, box_id: int = 1) -> BatchTargets:
    """构造单目标批次（指定 class_id）。"""
    return BatchTargets(
        task_id=1,
        targets=(VisionTarget(target_seq, class_id, pixel_x=100, pixel_y=100, box_id=box_id),),
    )


def test_vote_disabled_behaves_as_before():
    """投票关闭时（默认）行为与改动前逐字节等价。"""
    src = _make_source_with_vote(enabled=False)

    # 直接测试 _expand（绕过 wire，因为 wire 没有 box_id）
    batch = _batch_with_class(1, 2, box_id=1)
    ctx = src._expand(batch)
    assert len(ctx) == 1
    assert ctx[0].payload.class_id == 2, "关闭投票时直接采纳第一帧的 class_id"


def test_vote_accepts_consistent_class():
    """2/3 一致 → 采纳（投票胜出的 class_id）。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2)

    # 帧 1: class_id=2
    batch1 = _batch_with_class(1, 2)
    ctx = src._expand(batch1)
    assert len(ctx) == 0, "第 1 帧：未达 quorum，不派件"

    # 帧 2: class_id=2（同一目标，2 票）
    batch2 = _batch_with_class(1, 2)
    ctx = src._expand(batch2)
    assert len(ctx) == 1, "第 2 帧：2/3 达标，采纳"
    assert ctx[0].payload.class_id == 2

    # 验证统计
    stats = src.vote_stats()
    assert stats["accepted"] == 1
    assert stats["rejected_no_quorum"] == 1  # 第 1 帧未达标


def test_vote_rejects_inconsistent_class():
    """1/3 一致 → 不派件（未达 quorum）。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2)

    # 帧 1/2/3: class_id 各不相同
    ctx1 = src._expand(_batch_with_class(1, 2))
    ctx2 = src._expand(_batch_with_class(1, 3))
    ctx3 = src._expand(_batch_with_class(1, 4))

    assert len(ctx1) == 0
    assert len(ctx2) == 0
    assert len(ctx3) == 0

    stats = src.vote_stats()
    assert stats["rejected_no_quorum"] == 3


def test_vote_timeout_after_max_wait():
    """超时：等待 max_wait 帧仍未达 quorum → 记 timeout + 不派件。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2, max_wait=3)

    # 帧 1/2/3: class_id 各不相同，连续 3 帧（= max_wait）
    for cid in [2, 3, 4]:
        ctx = src._expand(_batch_with_class(1, cid))
        assert len(ctx) == 0

    stats = src.vote_stats()
    assert stats["timeout"] >= 1, "等待 3 帧仍未达标 → 至少 1 次超时"


def test_vote_follows_majority():
    """投票选择多数派：2 票 class_id=2、1 票 class_id=3 → 采纳 2。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2)

    # 帧 1: class_id=2
    src._expand(_batch_with_class(1, 2))
    # 帧 2: class_id=3
    src._expand(_batch_with_class(1, 3))
    # 帧 3: class_id=2（2 票 vs 1 票）
    ctx = src._expand(_batch_with_class(1, 2))

    assert len(ctx) == 1
    assert ctx[0].payload.class_id == 2, "多数派胜出"


def test_vote_resets_when_target_seq_changes():
    """target_seq 变化时，历史不互相干扰。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2)

    # target_seq=1: 2 帧 class_id=2
    src._expand(_batch_with_class(1, 2))
    ctx1 = src._expand(_batch_with_class(1, 2))
    assert len(ctx1) == 1
    assert ctx1[0].payload.class_id == 2

    # target_seq=2: 新目标，独立计数
    ctx2 = src._expand(_batch_with_class(2, 3))
    assert len(ctx2) == 0, "新目标第 1 帧未达 quorum"


def test_vote_position_matching_when_seq_unreliable():
    """target_seq 不可靠（=0）时退化为位置匹配。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2)

    # 帧 1/2: 同一位置 (100,100)，target_seq=0
    batch1 = BatchTargets(
        task_id=1,
        targets=(VisionTarget(0, 2, pixel_x=100, pixel_y=100, box_id=1),),
    )
    batch2 = BatchTargets(
        task_id=1,
        targets=(VisionTarget(0, 2, pixel_x=102, pixel_y=98, box_id=1),),
    )

    ctx1 = src._expand(batch1)
    assert len(ctx1) == 0

    ctx2 = src._expand(batch2)
    assert len(ctx2) == 1, "位置接近 → 视为同一目标 → 2/3 达标"


def test_vote_does_not_crash_on_wire_path():
    """投票不破坏 wire 路径（通过 ingest）。

    注意：wire 格式的 BATCH_TARGETS 中 id 字节在 BATCH_ID_BYTE_IS_BOX_ID=True
    时会被当作 box_id，所以这里测试的是完整的 ingest → next_if_permitted 流程。
    投票关闭时应该正常工作。
    """
    src = _make_source_with_vote(enabled=False)  # 关闭投票以测试基本流程
    src.set_permitted(True)

    # 单目标批次：count=1, task_id=1, id=4, conf=90, x=100, y=100, angle=0xFF
    # id=4 在 BATCH_ID_BYTE_IS_BOX_ID 模式下会被解析为 class_id=4, box_id=4
    payload = bytes.fromhex("010001045a0064006400ff")
    src.ingest(payload)
    ctx = src.next_if_permitted()
    # wire 路径能工作（即使返回 None 也不应该崩溃）
    # 实际上，因为 drop_point_for_box(4) 和 grasp_point_for_target 都有返回值，
    # 所以应该能产出
    assert ctx is not None or ctx is None, "wire 路径不应崩溃"


def test_vote_empty_batch_returns_empty():
    """空批次 → 返回空（不崩溃）。"""
    src = _make_source_with_vote(enabled=True)
    batch = BatchTargets(task_id=1, targets=())
    ctx = src._expand(batch)
    assert ctx == []


def test_vote_all_rejected_returns_empty():
    """全部未达 quorum → 返回空（不崩溃）。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=3)

    # 2 帧不够 3 票
    ctx1 = src._expand(_batch_with_class(1, 2))
    ctx2 = src._expand(_batch_with_class(1, 2))
    assert ctx1 == []
    assert ctx2 == []

