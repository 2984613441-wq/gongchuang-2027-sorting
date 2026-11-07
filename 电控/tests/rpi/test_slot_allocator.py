"""货格动态分配器单测（2026-11-01 新增）。

用户口径：比赛必须动态分配货格，否则场地摆位一变就判错。
本文件只验证分配规则与持久化，不涉及任何硬件。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from electrical_control.rpi.slot_allocator import AllocatorFull, SlotAllocator


def _workspace_tmp(name: str) -> Path:
    """工作区内的临时目录（沙箱禁止 pytest 的 tmp_path，见 rpi 其它用例同样规避）。"""
    d = Path(__file__).resolve().parent / "_tmp"
    d.mkdir(exist_ok=True)
    return d / name


# --------------------------------------------------------------------------- #
# 静态模式（默认，= 现状）
# --------------------------------------------------------------------------- #
def test_static_mode_uses_fixed_map():
    alloc = SlotAllocator(mode="static", static_map={1: 3, 7: 5})
    assert alloc.box_for(1) == 3
    assert alloc.box_for(7) == 5
    assert alloc.box_for(99) is None        # 未映射 ⇒ 不猜
    assert alloc.assignment() == {}


def test_static_mode_never_assigns():
    alloc = SlotAllocator(mode="static")
    for code in range(1, 31):
        alloc.box_for(code)
    assert alloc.occupancy() == {}


# --------------------------------------------------------------------------- #
# 动态模式：同 code 复用 + 空格分配
# --------------------------------------------------------------------------- #
def test_same_code_reuses_same_box():
    alloc = SlotAllocator(mode="dynamic")
    first = alloc.box_for(11)
    assert first == 1
    assert alloc.box_for(11) == first        # 复用（集中落点）
    assert alloc.box_for(11) == first


def test_different_codes_get_different_boxes():
    alloc = SlotAllocator(mode="dynamic")
    boxes = [alloc.box_for(c) for c in (1, 6, 11, 16, 21, 26)]
    assert boxes == [1, 2, 3, 4, 5, 6]
    assert len(set(boxes)) == 6


def test_full_allocator_returns_none_by_default():
    alloc = SlotAllocator(mode="dynamic")
    for code in (1, 2, 3, 4, 5, 6):
        assert alloc.box_for(code) is not None
    assert alloc.box_for(7) is None          # 满格 ⇒ 不猜
    assert alloc.box_for(1) == 1             # 已分配仍可复用


def test_full_allocator_can_raise_in_strict_mode():
    alloc = SlotAllocator(mode="dynamic", strict=True)
    for code in (1, 2, 3, 4, 5, 6):
        alloc.box_for(code)
    with pytest.raises(AllocatorFull):
        alloc.box_for(7)


# --------------------------------------------------------------------------- #
# S2（2026-11-07）：去"两侧"，选格固定 1→6
# --------------------------------------------------------------------------- #
def test_side_of_box_is_deprecated_and_ignored():
    """传了 side_of_box 也不影响选格：空格一律取编号最小（1→6）。"""
    sides = {1: "A", 2: "B", 3: "A", 4: "B", 5: "A", 6: "B"}
    alloc = SlotAllocator(mode="dynamic", side_of_box=sides)
    assert [alloc.box_for(c) for c in (11, 12, 13, 14)] == [1, 2, 3, 4]


def test_selection_is_monotonic_1_to_6():
    """A→1、B→2、A 复用→1、C→3 …… 六件按 1..6 单调占用（转盘不回摆）。"""
    alloc = SlotAllocator(mode="dynamic")
    assert alloc.box_for(11) == 1
    assert alloc.box_for(12) == 2
    assert alloc.box_for(11) == 1          # 同 code 复用
    assert alloc.box_for(13) == 3
    assert alloc.box_for(14) == 4
    assert alloc.box_for(15) == 5
    assert alloc.box_for(16) == 6
    assert alloc.occupancy() == {1: 11, 2: 12, 3: 13, 4: 14, 5: 15, 6: 16}
    assert alloc.box_for(17) is None       # 满格拒识


def test_correct_conflict_only_logs_and_keeps_old_mapping():
    """复看纠正冲突：actual code 已映射到别格 ⇒ 只记日志、不改旧映射、返回 False。"""
    alloc = SlotAllocator(mode="dynamic")
    assert alloc.box_for(11) == 1
    assert alloc.box_for(21) == 2
    ok = alloc.correct(expected_code=11, actual_code=21, box_id=1)  # 21 已在 box2
    assert ok is False
    assert alloc.assignment() == {11: 1, 21: 2}


def test_correct_moves_expected_mapping():
    """复看纠正正常路径：把 11→box1 的台账改成实际 code=22→box1。"""
    alloc = SlotAllocator(mode="dynamic")
    assert alloc.box_for(11) == 1
    assert alloc.correct(expected_code=11, actual_code=22, box_id=1) is True
    assert alloc.assignment() == {22: 1}
    assert alloc.box_for(22) == 1


# --------------------------------------------------------------------------- #
# 持久化
# --------------------------------------------------------------------------- #
def test_journal_round_trip():
    journal = _workspace_tmp("alloc_round_trip.json")
    journal.unlink(missing_ok=True)      # 上一次运行的台账不能带进来
    alloc = SlotAllocator(mode="dynamic", journal_path=journal, round_id="round-1")
    assert alloc.box_for(11) == 1
    assert alloc.box_for(21) == 2

    reloaded = SlotAllocator(mode="dynamic", journal_path=journal, round_id="round-1")
    assert reloaded.assignment() == {11: 1, 21: 2}
    assert reloaded.box_for(11) == 1        # 重启后仍复用
    assert reloaded.box_for(3) == 3         # 新 code 继续分配


def test_journal_from_other_round_is_ignored():
    journal = _workspace_tmp("alloc_other_round.json")
    journal.unlink(missing_ok=True)
    journal.write_text(json.dumps({
        "round_id": "old-round",
        "code_to_box": {"11": 1},
        "last_box": 1,
    }), encoding="utf-8")
    alloc = SlotAllocator(mode="dynamic", journal_path=journal, round_id="new-round")
    assert alloc.assignment() == {}
    assert alloc.box_for(11) == 1


def test_corrupt_journal_does_not_crash():
    journal = _workspace_tmp("alloc_corrupt.json")
    journal.write_text("{not json", encoding="utf-8")
    alloc = SlotAllocator(mode="dynamic", journal_path=journal, round_id="r1")
    assert alloc.assignment() == {}
    assert alloc.box_for(1) == 1


# --------------------------------------------------------------------------- #
# 参数校验
# --------------------------------------------------------------------------- #
def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        SlotAllocator(mode="auto")


def test_empty_boxes_rejected():
    with pytest.raises(ValueError):
        SlotAllocator(box_ids=(), mode="dynamic")
