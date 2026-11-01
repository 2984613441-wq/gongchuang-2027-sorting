"""PlaceEye（落料位副相机）配置与判色统计的单测（2026-11-01 新增）。

不依赖 cv2：只测配置解析与 HSV 众数统计（抓帧函数在有 cv2 的 Pi 上再测）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from electrical_control.rpi.place_eye import (
    PlaceEyeConfig,
    PlaceEyeUnavailable,
    capture_frame,
    load_place_eye_config,
    majority_color,
    sample_hsv_grid,
)


def _ini(name: str, body: str) -> Path:
    d = Path(__file__).resolve().parent / "_tmp"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    return p


_BASE = """
[PlaceEye]
enabled = {enabled}
device = /dev/video2
width = 1280
height = 720
fps = 30
roi = 500, 400, 200, 150
grid = 5
min_votes = 3
"""


# --------------------------------------------------------------------------- #
# 配置解析
# --------------------------------------------------------------------------- #
def test_missing_file_disables():
    assert load_place_eye_config("no_such_file.ini") is None


def test_missing_section_disables():
    p = _ini("pe_no_section.ini", "[DropPoints]\n1 = 10, 20\n")
    assert load_place_eye_config(p) is None


def test_enabled_false_disables():
    p = _ini("pe_disabled.ini", _BASE.format(enabled="false"))
    assert load_place_eye_config(p) is None


def test_valid_config_parsed():
    p = _ini("pe_ok.ini", _BASE.format(enabled="true"))
    cfg = load_place_eye_config(p)
    assert cfg is not None
    assert cfg.enabled is True
    assert cfg.device == "/dev/video2"
    assert cfg.roi == (500, 400, 200, 150)
    assert cfg.grid == 5 and cfg.min_votes == 3
    assert cfg.is_usable() is True


@pytest.mark.parametrize("roi", ["", "1,2,3", "10,20,-5,30", "0,0,0,0", "a,b,c,d"])
def test_bad_roi_disables(roi):
    body = _BASE.format(enabled="true").replace("roi = 500, 400, 200, 150",
                                                "roi = %s" % roi)
    assert load_place_eye_config(_ini("pe_bad_roi.ini", body)) is None


def test_roi_beyond_frame_disables():
    body = _BASE.format(enabled="true").replace("roi = 500, 400, 200, 150",
                                                "roi = 1200, 700, 200, 150")
    assert load_place_eye_config(_ini("pe_roi_oob.ini", body)) is None


def test_bad_number_disables():
    body = _BASE.format(enabled="true").replace("grid = 5", "grid = abc")
    assert load_place_eye_config(_ini("pe_bad_num.ini", body)) is None


def test_inline_comment_tolerated():
    body = _BASE.format(enabled="true").replace(
        "roi = 500, 400, 200, 150",
        "roi = 500, 400, 200, 150   # 【实测】落料位 ROI")
    cfg = load_place_eye_config(_ini("pe_comment.ini", body))
    assert cfg is not None and cfg.roi == (500, 400, 200, 150)


# --------------------------------------------------------------------------- #
# HSV 众数统计（cv2 口径：H 0..179）
# --------------------------------------------------------------------------- #
def test_majority_red():
    pixels = [(0, 200, 200)] * 6 + [(110, 200, 200)]
    color, votes, total = majority_color(pixels, min_votes=3)
    assert color == 1 and votes == 6 and total == 7


def test_majority_rejects_noise_below_min_votes():
    pixels = [(0, 200, 200)] * 2 + [(110, 200, 200)] * 2
    color, votes, _ = majority_color(pixels, min_votes=3)
    assert color == 0 and votes == 2


def test_majority_all_unknown():
    pixels = [(0, 10, 10)] * 5           # 全太暗
    assert majority_color(pixels, min_votes=1) == (0, 0, 5)


def test_majority_empty():
    assert majority_color([], min_votes=1) == (0, 0, 0)


def test_majority_ignores_malformed_pixels():
    pixels = [None, (1, 2), (110, 200, 200), (110, 200, 200), (110, 200, 200)]
    color, votes, total = majority_color(pixels, min_votes=3)
    # 畸形像素被跳过、不计入 total（total = 可解析的像素数）
    assert color == 4 and votes == 3 and total == 3


def test_majority_accepts_place_eye_min_votes_default():
    pixels = [(60, 200, 200)] * 3        # 绿 ×3
    color, votes, _ = majority_color(pixels)
    assert color == 3 and votes == 3


# --------------------------------------------------------------------------- #
# cv2 相关：无 cv2 时应抛明确异常而不是崩
# --------------------------------------------------------------------------- #
def test_capture_without_cv2_raises_place_eye_unavailable():
    cfg = PlaceEyeConfig(enabled=True, device="/dev/video2", width=1280,
                         height=720, fps=30, roi=(0, 0, 10, 10))
    try:
        import cv2  # noqa: F401
    except Exception:
        with pytest.raises(PlaceEyeUnavailable):
            capture_frame(cfg)
        return
    # 有 cv2 但没相机 ⇒ 同样应当是 PlaceEyeUnavailable
    with pytest.raises(PlaceEyeUnavailable):
        capture_frame(cfg)


def test_capture_disabled_config_raises():
    cfg = PlaceEyeConfig(enabled=False, device="/dev/video2", width=1280,
                         height=720, fps=30, roi=None)
    with pytest.raises(PlaceEyeUnavailable):
        capture_frame(cfg)
