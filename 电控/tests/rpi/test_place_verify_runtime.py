"""落料位复看运行时单测（2026-11-01 新增）。

用注入的 frame_provider 造假帧（无需 cv2/相机），验证三档开关、三态计数、
台账纠正与失败降级。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from electrical_control.rpi.place_eye import PlaceEyeConfig
from electrical_control.rpi.place_verify_runtime import MODES, PlaceVerifyRuntime
from electrical_control.rpi.slot_allocator import SlotAllocator


def _cfg() -> PlaceEyeConfig:
    return PlaceEyeConfig(enabled=True, device="/dev/video2", width=1280,
                          height=720, fps=30, roi=(10, 10, 20, 20), grid=2,
                          min_votes=1)


class _FakeFrame:
    """最小假帧：只有 shape 与 __getitem__（sample_hsv_grid 需要的）。

    由于 sample_hsv_grid 依赖 cv2.cvtColor，这里直接把 pixel 值当 HSV 用 ——
    通过 monkeypatch 掉 sample_hsv_grid 来隔离 cv2（见 _runtime）。
    """

    def __init__(self, value=(0, 200, 200)):
        self.value = value
        self.shape = (100, 100, 3)

    def __getitem__(self, _idx):
        return self.value


def _runtime(mode: str, color: int, *, allocator=None):
    """把 sample_hsv_grid 替换成「整块 ROI 都是同一个颜色」的假实现。"""
    import electrical_control.rpi.place_eye as pe

    def fake_sample(frame, roi, grid=5):
        return [frame.value] * (grid * grid)

    orig = pe.sample_hsv_grid
    pe.sample_hsv_grid = fake_sample
    palette = {
        1: (0, 220, 220), 2: (20, 220, 220), 3: (60, 220, 220),
        4: (110, 220, 220), 5: (0, 20, 230), 0: (0, 0, 10),
    }
    rt = PlaceVerifyRuntime(
        mode, cfg=_cfg(), allocator=allocator,
        frame_provider=lambda cfg: _FakeFrame(palette[color]),
    )
    return rt, orig, pe


# --------------------------------------------------------------------------- #
# 开关
# --------------------------------------------------------------------------- #
def test_off_mode_does_nothing():
    rt = PlaceVerifyRuntime("off")
    assert rt.enabled() is False
    assert rt.on_item_result(target_seq=1, class_id=11) is None
    assert rt.stats()["checked"] == 0


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        PlaceVerifyRuntime("watch")
    assert MODES == ("off", "observe", "correct")


# --------------------------------------------------------------------------- #
# 三态
# --------------------------------------------------------------------------- #
def test_match_counted():
    rt, orig, pe = _runtime("observe", 1)      # 期望 11=圆柱+红，看到红
    try:
        out = rt.on_item_result(target_seq=1, class_id=11, box_id=1)
    finally:
        pe.sample_hsv_grid = orig
    assert out is not None and out["verdict"] == "MATCH"
    assert rt.stats()["match"] == 1 and rt.stats()["checked"] == 1


def test_mismatch_counted_without_correction_in_observe():
    alloc = SlotAllocator(mode="dynamic")
    rt, orig, pe = _runtime("observe", 4, allocator=alloc)   # 看到蓝
    try:
        out = rt.on_item_result(target_seq=1, class_id=11, box_id=1)
    finally:
        pe.sample_hsv_grid = orig
    assert out["verdict"] == "MISMATCH"
    assert out["observed_code"] == 14          # 推断：圆柱+蓝
    assert rt.stats()["mismatch"] == 1
    assert rt.stats()["corrected"] == 0        # observe 不改台账
    assert alloc.assignment() == {}


def test_correct_mode_fixes_ledger():
    alloc = SlotAllocator(mode="dynamic")
    box = alloc.box_for(11)
    rt, orig, pe = _runtime("correct", 4, allocator=alloc)
    try:
        out = rt.on_item_result(target_seq=1, class_id=11, box_id=box)
    finally:
        pe.sample_hsv_grid = orig
    assert out["verdict"] == "MISMATCH"
    assert rt.stats()["corrected"] == 1
    assert alloc.assignment() == {14: box}


def test_unknown_color_is_counted_unknown():
    rt, orig, pe = _runtime("observe", 0)      # 判不出
    try:
        out = rt.on_item_result(target_seq=1, class_id=11, box_id=1)
    finally:
        pe.sample_hsv_grid = orig
    assert out["verdict"] == "UNKNOWN"
    assert rt.stats()["unknown"] == 1
    assert rt.stats()["mismatch"] == 0


# --------------------------------------------------------------------------- #
# 跳过与降级
# --------------------------------------------------------------------------- #
def test_failed_result_is_skipped():
    rt, orig, pe = _runtime("observe", 1)
    try:
        assert rt.on_item_result(target_seq=1, class_id=11, result_code=3) is None
    finally:
        pe.sample_hsv_grid = orig
    assert rt.stats()["skipped"] == 1 and rt.stats()["checked"] == 0


def test_no_config_counts_unknown():
    rt = PlaceVerifyRuntime("observe", cfg=None)
    assert rt.on_item_result(target_seq=1, class_id=11) is None
    assert rt.stats()["unknown"] == 1


def test_frame_provider_exception_counts_unknown():
    def boom(cfg):
        raise RuntimeError("相机炸了")

    rt = PlaceVerifyRuntime("observe", cfg=_cfg(), frame_provider=boom)
    out = rt.on_item_result(target_seq=1, class_id=11)
    assert out["verdict"] == "UNKNOWN"
    assert rt.stats()["unknown"] == 1


def test_summary_text_contains_counts():
    rt, orig, pe = _runtime("observe", 1)
    try:
        rt.on_item_result(target_seq=1, class_id=11, box_id=1)
    finally:
        pe.sample_hsv_grid = orig
    text = rt.summary()
    assert "MATCH 1" in text and "检查 1" in text
