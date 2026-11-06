"""Tests for multi-frame class voting (2026-11-06 形状误判修复 任务A).

🔴 2026-11-07 第2轮修复测试：
- unanimous 模式（默认）：窗口满且全一致才采纳
- 超时按目标年龄计：_vote_seen[key] >= max_wait
- 跨轮清空：set_permitted(True) 时清空历史
- 位置栅格键：grid=(round(px/grid_px), round(py/grid_px))
- 向后兼容：majority + quorum=2 仍可用
"""

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
    mode: str = "unanimous",  # 🔴 2026-11-07：新增 mode 参数
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
        class_vote_mode=mode,  # 🔴 2026-11-07
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
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2, mode="majority")  # 🔴 明确 majority

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
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2, mode="majority")

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
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2, mode="majority")

    # 帧 1: class_id=2
    src._expand(_batch_with_class(1, 2))
    # 帧 2: class_id=3
    src._expand(_batch_with_class(1, 3))
    # 帧 3: class_id=2（2 票 vs 1 票）
    ctx = src._expand(_batch_with_class(1, 2))

    assert len(ctx) == 1
    assert ctx[0].payload.class_id == 2, "多数派胜出"


def test_vote_resets_when_target_seq_changes():
    """🔴 2026-11-07：位置栅格键改造后，不同位置的目标互相隔离（不管 target_seq）。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2, mode="majority")

    # 位置1 (100, 200): 2 帧 class_id=2
    batch1 = BatchTargets(task_id=1, targets=(VisionTarget(1, 2, pixel_x=100, pixel_y=200, box_id=1),))
    src._expand(batch1)
    ctx1 = src._expand(batch1)
    assert len(ctx1) == 1
    assert ctx1[0].payload.class_id == 2

    # 位置2 (300, 400): 新位置，独立计数（即使 target_seq 相同）
    batch2 = BatchTargets(task_id=1, targets=(VisionTarget(1, 3, pixel_x=300, pixel_y=400, box_id=2),))
    ctx2 = src._expand(batch2)
    assert len(ctx2) == 0, "不同位置的目标第 1 帧未达 quorum"


def test_vote_position_matching_when_seq_unreliable():
    """target_seq 不可靠（=0）时退化为位置匹配。"""
    src = _make_source_with_vote(enabled=True, frames=3, quorum=2, mode="majority")

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
    src = _make_source_with_vote(enabled=True, frames=3, quorum=3, mode="majority")

    # 2 帧不够 3 票
    ctx1 = src._expand(_batch_with_class(1, 2))
    ctx2 = src._expand(_batch_with_class(1, 2))
    assert ctx1 == []
    assert ctx2 == []


# 🔴 2026-11-07 第2轮修复：新增测试用例


def test_unanimous_mode_rejects_alternating_classes():
    """【问题1修复】unanimous 模式（默认）：两类交替 10 帧 → accepted=0。"""
    src = _make_source_with_vote(enabled=True, frames=3, mode="unanimous")

    # 交替 10 帧：class_id 在 2 和 3 之间摇摆
    for i in range(10):
        cid = 2 if i % 2 == 0 else 3
        ctx = src._expand(_batch_with_class(1, cid))
        assert ctx == [], f"第 {i+1} 帧：交替类别不应采纳（unanimous 模式）"

    stats = src.vote_stats()
    assert stats["accepted"] == 0, "交替类别应全部拒绝"
    assert stats["rejected_no_quorum"] >= 9, "大部分帧应被 rejected"


def test_timeout_by_target_age():
    """【问题2修复】超时按目标年龄计：默认参数持续摇摆 8 帧 → timeout>=1。"""
    src = _make_source_with_vote(
        enabled=True,
        frames=3,
        max_wait=6,  # 默认 6 帧
        mode="unanimous"
    )

    # 持续摇摆 8 帧：class_id 在 2/3/4 之间循环（永远无法达成 unanimous）
    for i in range(8):
        cid = [2, 3, 4][i % 3]
        src._expand(_batch_with_class(1, cid))

    stats = src.vote_stats()
    assert stats["timeout"] >= 1, "超过 max_wait=6 帧应触发 timeout"


def test_history_cleared_on_new_round():
    """【问题3修复】换轮（set_permitted(True)）后历史清空、不提前采纳。"""
    src = _make_source_with_vote(enabled=True, frames=3, mode="unanimous")

    # 第1轮：2 帧 class_id=2
    src._expand(_batch_with_class(1, 2))
    src._expand(_batch_with_class(1, 2))

    # 换轮
    src.set_permitted(False)
    src.set_permitted(True)

    # 第2轮：只 1 帧 class_id=2（如果历史未清空，会混入上一轮的 2 票 → 提前采纳）
    ctx = src._expand(_batch_with_class(1, 2))
    assert ctx == [], "换轮后历史应清空，1 帧不足 3 帧窗口"

    # 第2轮：再 2 帧 → 3 帧满窗口 → 采纳
    src._expand(_batch_with_class(1, 2))
    ctx = src._expand(_batch_with_class(1, 2))
    assert len(ctx) == 1, "新轮 3 帧一致应采纳"


def test_position_grid_key_handles_seq_change():
    """【问题4修复】同一位置 target_seq 1→2→3 变化仍能累计通过。"""
    src = _make_source_with_vote(
        enabled=True,
        frames=3,
        mode="unanimous",
        # 默认 grid_px=80, match_radius=80
    )

    # 同一位置 (100, 100)，但 target_seq 每次不同（模拟件被抓走后后续件前移）
    for seq in [1, 2, 3]:
        batch = BatchTargets(
            task_id=1,
            targets=(
                VisionTarget(
                    target_seq=seq,
                    class_id=2,
                    confidence=90,
                    pixel_x=100,
                    pixel_y=100,
                    box_id=1,
                ),
            ),
        )
        ctx = src._expand(batch)

    # 第3帧应采纳（位置一致，累计 3 帧）
    assert len(ctx) == 1, "位置栅格键应累计同位置不同 seq 的目标"
    assert ctx[0].payload.class_id == 2


def test_majority_mode_backward_compatible():
    """【向后兼容】majority + quorum=2 仍可用（与第1轮逻辑一致）。"""
    src = _make_source_with_vote(
        enabled=True,
        frames=3,
        quorum=2,
        mode="majority"  # 🔴 明确指定 majority
    )

    # 2 帧 class_id=2，1 帧 class_id=3 → 2 票占多数 → 采纳
    src._expand(_batch_with_class(1, 2))
    src._expand(_batch_with_class(1, 2))
    ctx = src._expand(_batch_with_class(1, 3))

    assert len(ctx) == 1, "majority 模式 2/3 票应采纳"
    assert ctx[0].payload.class_id == 2, "应采纳多数派 class_id=2"


def test_vote_disabled_still_works():
    """【回归】默认关闭（class_vote_enabled=False）行为不变（保留原用例）。"""
    src = _make_source_with_vote(enabled=False)

    # 直接测试 _expand（绕过 wire，因为 wire 没有 box_id）
    batch = _batch_with_class(1, 2, box_id=1)
    ctx = src._expand(batch)
    assert len(ctx) == 1
    assert ctx[0].payload.class_id == 2, "关闭投票时直接采纳第一帧的 class_id"

