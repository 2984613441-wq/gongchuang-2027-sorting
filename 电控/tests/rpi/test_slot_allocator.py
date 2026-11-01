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
# 转盘换挡优化：优先与上次同侧
# --------------------------------------------------------------------------- #
def test_prefers_same_side_to_reduce_turntable_moves():
    sides = {1: "A", 2: "B", 3: "A", 4: "B", 5: "A", 6: "B"}
    alloc = SlotAllocator(mode="dynamic", side_of_box=sides)
    assert alloc.box_for(11) == 1                 # 首次取最小格 → A 侧
    assert alloc.box_for(12) == 3                 # A 侧还有空格 ⇒ 优先 A（不是 2）
    assert alloc.box_for(13) == 5
    assert alloc.box_for(14) == 2                 # A 侧满 ⇒ 才去 B


# --------------------------------------------------------------------------- #
# 持久化
# --------------------------------------------------------------------------- #
def test_journal_round_trip():
    journal = _workspace_tmp("alloc_round_trip.json")
    alloc = SlotAllocator(mode="dynamic", journal_path=journal, round_id="round-1")
    assert alloc.box_for(11) == 1
    assert alloc.box_for(21) == 2

    reloaded = SlotAllocator(mode="dynamic", journal_path=journal, round_id="round-1")
    assert reloaded.assignment() == {11: 1, 21: 2}
    assert reloaded.box_for(11) == 1        # 重启后仍复用
    assert reloaded.box_for(3) == 3         # 新 code 继续分配


def test_journal_from_other_round_is_ignored():
    journal = _workspace_tmp("alloc_other_round.json")
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
