"""落料位颜色判决单测（2026-11-01 新增，阈值【待实测】）。

cv2 口径：H∈[0,179]、S/V∈[0,255]。
"""

from __future__ import annotations

import pytest

from electrical_control.rpi.color_judge import (
    COLOR_NAMES,
    hsv_to_color,
    infer_code_from_color,
    shape_from_code,
)


# --------------------------------------------------------------------------- #
# 典型颜色（阈值是待实测估计值，用例只验证「方向正确」）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("h,s,v,expected", [
    (0, 200, 200, 1),      # 红
    (175, 200, 200, 1),    # 红（跨 0 的另一侧）
    (20, 200, 200, 2),     # 黄
    (60, 200, 200, 3),     # 绿
    (110, 200, 200, 4),    # 蓝
    (0, 20, 240, 5),       # 白：低饱和高亮
    (0, 10, 120, 0),       # 灰：不猜
    (0, 200, 20, 0),       # 太暗：不猜
    (150, 200, 200, 0),    # 紫/过渡带：不猜
])
def test_hsv_to_color_directions(h, s, v, expected):
    assert hsv_to_color(h, s, v) == expected


def test_color_names_complete():
    assert set(COLOR_NAMES) == {1, 2, 3, 4, 5}


def test_h_out_of_range_is_wrapped():
    assert hsv_to_color(360, 200, 200) == hsv_to_color(0, 200, 200)


def test_sv_clamped():
    assert hsv_to_color(110, 999, 999) in (4, 0)


# --------------------------------------------------------------------------- #
# code 推导
# --------------------------------------------------------------------------- #
def test_shape_from_code():
    assert shape_from_code(1) == 1
    assert shape_from_code(5) == 1
    assert shape_from_code(6) == 2
    assert shape_from_code(30) == 6
    assert shape_from_code(0) is None
    assert shape_from_code(31) is None


def test_infer_code_keeps_shape_changes_color():
    # 期望 圆柱+红 = 11；观测到蓝色 ⇒ 推断 圆柱+蓝 = 14
    assert infer_code_from_color(11, 4) == 14
    # 期望 四面体+白 = 30；观测到绿 ⇒ 推断 四面体+绿 = 28
    assert infer_code_from_color(30, 3) == 28


@pytest.mark.parametrize("code,color", [(0, 1), (31, 1), (11, 0), (11, 6)])
def test_infer_code_rejects_invalid(code, color):
    assert infer_code_from_color(code, color) is None
