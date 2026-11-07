"""挡板巡检（S3 骨架）单测：纯逻辑 + 合成图，不碰相机/网络/硬件。

覆盖：差分判据、ROI 边界、基准帧不可用时的兜底、三态语义（UNKNOWN ≠ 没有）、
配置解析 fail-closed、D7 动作映射。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from electrical_control.rpi.barrier_check import (
    BarrierCheckError,
    BarrierChecker,
    BarrierConfig,
    BarrierState,
    judge_frame,
    load_barrier_config,
    occupied_action,
    parse_roi,
    unknown_action,
)

ROI = (50, 50, 100, 100)   # x,y,w,h


def _blank(h: int = 200, w: int = 200) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _with_block(h: int = 200, w: int = 200, *, x0: int = 80, y0: int = 80,
                size: int = 40, color=(0, 0, 255)) -> np.ndarray:
    img = _blank(h, w)
    img[y0:y0 + size, x0:x0 + size] = color
    return img


def _tmp_path(name: str) -> Path:
    d = Path(__file__).resolve().parent / "_tmp"
    d.mkdir(exist_ok=True)
    return d / name


# --------------------------------------------------------------------------- #
# 判定：基准帧差分
# --------------------------------------------------------------------------- #
def test_same_frame_is_clear():
    frame = _blank()
    state, ev = judge_frame(frame, frame.copy(), ROI)
    assert state is BarrierState.CLEAR
    assert ev["diff_ratio"] == 0.0


def test_block_inside_roi_is_occupied():
    state, ev = judge_frame(_with_block(), _blank(), ROI, diff_threshold=0.02)
    assert state is BarrierState.OCCUPIED
    assert ev["diff_ratio"] > 0.02


def test_block_outside_roi_is_clear():
    # 块在 (0,0)，ROI 从 (50,50) 开始 ⇒ 不影响判定
    state, _ev = judge_frame(_with_block(x0=0, y0=0), _blank(), ROI)
    assert state is BarrierState.CLEAR


def test_threshold_respected():
    state, ev = judge_frame(_with_block(), _blank(), ROI, diff_threshold=0.9)
    assert state is BarrierState.CLEAR, ev   # 占比不够高 ⇒ 视为没变化


def test_roi_out_of_bounds_raises():
    with pytest.raises(BarrierCheckError):
        judge_frame(_blank(), _blank(), (150, 150, 100, 100))


def test_baseline_shape_mismatch_falls_back_to_unknown():
    """基准帧尺寸不对 ⇒ 差分不可用、又只有灰度块 ⇒ 不猜"没有"，返回 UNKNOWN。"""
    state, ev = judge_frame(_with_block(), _blank(h=100, w=100), ROI)
    assert state is BarrierState.UNKNOWN
    assert "baseline_error" in ev


# --------------------------------------------------------------------------- #
# 判定：无基准帧时的 HSV 兜底
# --------------------------------------------------------------------------- #
def test_hsv_fallback_detects_colorful_region_without_baseline():
    frame = _with_block(color=(0, 0, 255))   # 大红色块，占 ROI 16%
    # 兜底阈值 0.25 ⇒ 16% 不够，应先 UNKNOWN；换成半个 ROI 的红块才判 OCCUPIED
    state, _ev = judge_frame(frame, None, ROI)
    assert state is BarrierState.UNKNOWN

    big = _blank()
    big[50:150, 50:150] = (0, 0, 255)        # ROI 全红
    state2, ev2 = judge_frame(big, None, ROI)
    assert state2 is BarrierState.OCCUPIED
    assert ev2["basis"] == "hsv_fallback"


def test_gray_image_without_baseline_is_unknown():
    state, _ev = judge_frame(_blank(), None, ROI)
    assert state is BarrierState.UNKNOWN


# --------------------------------------------------------------------------- #
# 配置解析（fail-closed）
# --------------------------------------------------------------------------- #
def _write_cfg(body: str) -> Path:
    p = _tmp_path("barrier_test.ini")
    p.write_text(body, encoding="utf-8")
    return p


def test_missing_section_defaults_to_off():
    p = _write_cfg("[Vision]\nconf = 0.4\n")
    cfg = load_barrier_config(p)
    assert cfg.mode == "off"
    assert cfg.enabled is False


def test_full_section_parsed():
    p = _write_cfg(
        "[BarrierCheck]\n"
        "mode = observe\n"
        "camera = cam2\n"
        "roi = 10, 20, 300, 200\n"
        "baseline = /home/pi/barrier_cam2_empty.jpg\n"
        "diff_threshold = 0.05\n"
        "on_unknown = stop\n"
        "snapshot_url = http://172.20.10.8:8080/snap\n"
    )
    cfg = load_barrier_config(p)
    assert cfg.enabled is True
    assert cfg.mode == "observe"
    assert cfg.camera == "cam2"
    assert cfg.roi == (10, 20, 300, 200)
    assert cfg.diff_threshold == 0.05
    assert cfg.on_unknown == "stop"


def test_mode_on_without_roi_or_baseline_rejected():
    with pytest.raises(BarrierCheckError):
        BarrierConfig(mode="observe")
    with pytest.raises(BarrierCheckError):
        BarrierConfig(mode="observe", roi=ROI, baseline_path=None,
                      snapshot_url="http://x/snap")


def test_invalid_mode_and_camera_rejected():
    with pytest.raises(ValueError):
        BarrierConfig(mode="auto")
    with pytest.raises(ValueError):
        BarrierConfig(camera="cam0")


def test_parse_roi_rules():
    assert parse_roi("10,20,30,40") == (10, 20, 30, 40)
    assert parse_roi("10，20，30，40") == (10, 20, 30, 40)   # 全角逗号
    with pytest.raises(BarrierCheckError):
        parse_roi("10,20,30")
    with pytest.raises(BarrierCheckError):
        parse_roi("10,20,0,40")


# --------------------------------------------------------------------------- #
# BarrierChecker：取图失败一律 UNKNOWN，绝不猜"没有"
# --------------------------------------------------------------------------- #
def _cfg(**kw) -> BarrierConfig:
    base = dict(mode="observe", roi=ROI, baseline_path="x.jpg",
                snapshot_url="http://x/snap")
    base.update(kw)
    return BarrierConfig(**base)


def test_provider_raising_is_unknown():
    def boom():
        raise OSError("相机超时")

    checker = BarrierChecker(_cfg(), boom, _blank())
    state, ev = checker.check()
    assert state is BarrierState.UNKNOWN
    assert "error" in ev


def test_provider_none_is_unknown():
    checker = BarrierChecker(_cfg(), lambda: None, _blank())
    state, _ev = checker.check()
    assert state is BarrierState.UNKNOWN


def test_checker_clear_and_occupied():
    baseline = _blank()
    checker = BarrierChecker(_cfg(), lambda: _blank(), baseline)
    assert checker.check()[0] is BarrierState.CLEAR

    occluded = BarrierChecker(_cfg(), lambda: _with_block(), baseline)
    assert occluded.check()[0] is BarrierState.OCCUPIED


def test_checker_rejects_off_mode():
    with pytest.raises(BarrierCheckError):
        BarrierChecker(BarrierConfig(), lambda: _blank())


# --------------------------------------------------------------------------- #
# D7 动作映射
# --------------------------------------------------------------------------- #
def test_occupied_action_follows_d7():
    assert occupied_action(has_code=True) == "treat_as_item"
    assert occupied_action(has_code=False) == "claw_stop"


def test_unknown_action_from_config():
    assert unknown_action(_cfg(on_unknown="continue")) == "continue"
    assert unknown_action(_cfg(on_unknown="stop")) == "stop"
