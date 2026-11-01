"""落料位复看判决 + 台账纠正的单测（2026-11-01 新增）。

用户口径：副相机在**落料位**复看（远端看不全没关系，落点看得全）。
本文件只验证纯逻辑：三态判决、阈值过滤、台账纠正与冲突保护。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from electrical_control.rpi.place_verifier import (
    PlaceCheck,
    Verdict,
    verify_place,
    verify_place_color,
)
from electrical_control.rpi.slot_allocator import SlotAllocator


def _journal(name: str) -> Path:
    d = Path(__file__).resolve().parent / "_tmp"
    d.mkdir(exist_ok=True)
    p = d / name
    p.unlink(missing_ok=True)
    return p


# --------------------------------------------------------------------------- #
# 三态判决
# --------------------------------------------------------------------------- #
def test_match_when_expected_code_seen():
    r = verify_place(11, [11])
    assert r.verdict is Verdict.MATCH
    assert r.observed_code == 11
    assert r.needs_ledger_fix is False


def test_match_when_expected_among_multiple():
    r = verify_place(11, [21, 11])
    assert r.verdict is Verdict.MATCH


def test_mismatch_reports_highest_conf_candidate():
    r = verify_place(11, [21, 26], confidences=[55, 88])
    assert r.verdict is Verdict.MISMATCH
    assert r.observed_code == 26           # 取置信度最高者供台账纠正
    assert r.needs_ledger_fix is True


def test_unknown_when_nothing_observed():
    r = verify_place(11, [])
    assert r.verdict is Verdict.UNKNOWN
    assert r.observed_code is None
    assert r.needs_ledger_fix is False


def test_unknown_when_all_below_min_conf():
    r = verify_place(11, [11], confidences=[30], min_conf=40)
    assert r.verdict is Verdict.UNKNOWN


def test_low_conf_noise_does_not_mask_real_match():
    r = verify_place(11, [11, 26], confidences=[90, 20], min_conf=40)
    assert r.verdict is Verdict.MATCH


@pytest.mark.parametrize("expected,observed,verdict", [
    (1, [1], Verdict.MATCH),
    (1, [2], Verdict.MISMATCH),
    (30, [30], Verdict.MATCH),
    (30, [1], Verdict.MISMATCH),
])
def test_boundary_codes(expected, observed, verdict):
    assert verify_place(expected, observed).verdict is verdict


def test_place_check_is_immutable_style():
    r = verify_place(11, [11])
    assert isinstance(r, PlaceCheck)
    assert r.expected_code == 11


# --------------------------------------------------------------------------- #
# 台账纠正
# --------------------------------------------------------------------------- #
def test_correct_moves_mapping_to_actual_code():
    alloc = SlotAllocator(mode="dynamic", journal_path=_journal("fix1.json"),
                          round_id="r1")
    box = alloc.box_for(11)                  # 以为 code=11 → box 1
    assert alloc.assignment() == {11: box}

    ok = alloc.correct(expected_code=11, actual_code=21, box_id=box)
    assert ok is True
    assert alloc.assignment() == {21: box}   # 同格复用从此按实际 code
    assert alloc.box_for(21) == box
    assert alloc.box_for(11) != box          # 旧的错误映射已解除


def test_correct_conflict_keeps_old_mapping():
    alloc = SlotAllocator(mode="dynamic", journal_path=_journal("fix2.json"),
                          round_id="r1")
    b1 = alloc.box_for(11)
    b2 = alloc.box_for(21)
    assert b1 != b2
    ok = alloc.correct(expected_code=11, actual_code=21, box_id=b1)
    assert ok is False                       # 冲突：不解静默覆盖
    assert alloc.assignment()[21] == b2
    assert alloc.assignment()[11] == b1


def test_correct_unknown_box_rejected():
    alloc = SlotAllocator(mode="dynamic", journal_path=_journal("fix3.json"),
                          round_id="r1")
    assert alloc.correct(11, 21, box_id=99) is False


def test_correct_persists_to_journal():
    journal = _journal("fix4.json")
    alloc = SlotAllocator(mode="dynamic", journal_path=journal, round_id="r1")
    box = alloc.box_for(11)
    assert alloc.correct(11, 21, box) is True

    reloaded = SlotAllocator(mode="dynamic", journal_path=journal, round_id="r1")
    assert reloaded.assignment() == {21: box}

# --------------------------------------------------------------------------- #
# 颜色级复看（副相机在落料位只判颜色）
# --------------------------------------------------------------------------- #
def test_color_match():
    r = verify_place_color(11, 1)          # 11 = 圆柱+红，观测红
    assert r.verdict is Verdict.MATCH
    assert r.observed_code == 11


def test_color_mismatch_infers_actual_code():
    r = verify_place_color(11, 4)          # 圆柱+红 → 观测蓝 ⇒ 推断 14
    assert r.verdict is Verdict.MISMATCH
    assert r.observed_code == 14
    assert r.needs_ledger_fix is True
    assert "推断" in r.detail


def test_color_unknown_does_nothing():
    r = verify_place_color(11, 0)
    assert r.verdict is Verdict.UNKNOWN
    assert r.observed_code is None
    assert r.needs_ledger_fix is False


@pytest.mark.parametrize("bad_color", [6, -1, 255])
def test_color_out_of_range_is_unknown(bad_color):
    assert verify_place_color(11, bad_color).verdict is Verdict.UNKNOWN


def test_color_mismatch_can_drive_ledger_fix():
    """颜色级 MISMATCH 的推断 code 能直接喂给台账纠正。"""
    alloc = SlotAllocator(mode="dynamic", journal_path=_journal("fix_color.json"),
                          round_id="r1")
    box = alloc.box_for(11)
    r = verify_place_color(11, 4)          # 推断 14
    assert alloc.correct(r.expected_code, r.observed_code, box) is True
    assert alloc.assignment() == {14: box}
