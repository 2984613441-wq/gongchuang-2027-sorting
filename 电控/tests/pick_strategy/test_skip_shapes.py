"""主动放弃难夹形状（skip_shapes）的单测（2026-11-02 新增）。

用户口径：为得分，圆柱(3)/圆锥(5) 不好夹，可以主动放弃。
关键约束（本轮实现的核心）：
1. 跳过的件**只从可决策集合里剔除**，仍留在 `frame.detections` 里当障碍物；
2. 默认 `skip_shapes = ()`，行为与改动前完全一致（可一键回退）；
3. `class_id_mode` 决定怎么由 class_id 反推形状（box_id 历史口径 / code 1..30）。
"""

from __future__ import annotations

import pytest

from conftest import DEMO_INI, det, frame
from electrical_control.pick_strategy.config import build_config
from electrical_control.pick_strategy.selector import (
    order_by_row_scan,
    shape_of_detection,
    usable_detections,
)


def _ini(name: str, **replaced) -> str:
    """基于 demo ini 生成临时变体（写进 tests/pick_strategy/_tmp，沙箱允许）。"""
    from pathlib import Path

    text = Path(DEMO_INI).read_text(encoding="utf-8")
    for key, value in replaced.items():
        old = None
        for line in text.splitlines():
            if line.strip().startswith(key + " "):
                old = line
                break
        assert old is not None, "demo ini 里找不到 %r" % key
        # 变体行也必须带来源标签（解析器 fail-closed）
        text = text.replace(old, "%s = %s  # 【待实测】测试变体" % (key, value), 1)
    d = Path(__file__).resolve().parent / "_tmp"
    d.mkdir(exist_ok=True)
    out = d / ("variant_" + name + ".ini")
    out.write_text(text, encoding="utf-8")
    return str(out)


# --------------------------------------------------------------------------- #
# 配置解析
# --------------------------------------------------------------------------- #
def test_default_skip_shapes_is_empty(demo_config):
    assert demo_config.skip_shapes == ()
    assert demo_config.class_id_mode == "box_id"


def test_parse_skip_shapes():
    cfg = build_config(_ini("skip_cylinder_cone", skip_shapes="3,5"))
    assert cfg.skip_shapes == (3, 5)


def test_parse_skip_shapes_dedup_and_sort():
    cfg = build_config(_ini("skip_dup", skip_shapes="5, 3, 5"))
    assert cfg.skip_shapes == (3, 5)


def test_parse_skip_shapes_fullwidth_comma():
    cfg = build_config(_ini("skip_fullwidth", skip_shapes="3，5"))
    assert cfg.skip_shapes == (3, 5)


@pytest.mark.parametrize("bad", ["0,3", "7", "a", "3,,7"])
def test_parse_skip_shapes_rejects_invalid(bad):
    from electrical_control.pick_strategy.config import ConfigError
    with pytest.raises(ConfigError):
        build_config(_ini("skip_bad", skip_shapes=bad))


def test_parse_class_id_mode_code():
    cfg = build_config(_ini("cid_code", class_id_mode="code"))
    assert cfg.class_id_mode == "code"


def test_parse_class_id_mode_invalid():
    from electrical_control.pick_strategy.config import ConfigError
    with pytest.raises(ConfigError):
        build_config(_ini("cid_bad", class_id_mode="shape"))


# --------------------------------------------------------------------------- #
# class_id → shape
# --------------------------------------------------------------------------- #
def test_shape_of_detection_box_id_mode(demo_config):
    assert shape_of_detection(det(1, 1, 0, 0, class_id=3), demo_config) == 3
    assert shape_of_detection(det(1, 1, 0, 0, class_id=7), demo_config) is None


def test_shape_of_detection_code_mode():
    cfg = build_config(_ini("cid_code2", class_id_mode="code"))
    # code 1..5 = 形状1，6..10 = 形状2，11..15 = 形状3（圆柱）
    assert shape_of_detection(det(1, 1, 0, 0, class_id=1), cfg) == 1
    assert shape_of_detection(det(1, 1, 0, 0, class_id=5), cfg) == 1
    assert shape_of_detection(det(1, 1, 0, 0, class_id=11), cfg) == 3
    assert shape_of_detection(det(1, 1, 0, 0, class_id=30), cfg) == 6
    assert shape_of_detection(det(1, 1, 0, 0, class_id=0), cfg) is None


# --------------------------------------------------------------------------- #
# 过滤行为
# --------------------------------------------------------------------------- #
def _four_pieces():
    # box_id 模式：class_id == 形状号；1=cube 3=cylinder 5=cone 6=tetra
    return (det(1, 1, 10.0, 30.0), det(2, 3, 20.0, 30.0),
            det(3, 5, 30.0, 30.0), det(4, 6, 40.0, 30.0))


def test_no_skip_keeps_everything(demo_config):
    fr = frame(1, _four_pieces())
    usable, notes = usable_detections(fr, demo_config)
    assert len(usable) == 4


def test_skip_cylinder_cone_filters_two():
    cfg = build_config(_ini("skip_35", skip_shapes="3,5"))
    fr = frame(1, _four_pieces())
    usable, notes = usable_detections(fr, cfg)
    shapes = [d.class_id for d in usable]
    assert shapes == [1, 6], "只保留 cube 与 tetrahedron"
    assert any("主动放弃" in n for n in notes)


def test_skipped_pieces_stay_in_frame_as_obstacles():
    cfg = build_config(_ini("skip_35_obstacle", skip_shapes="3,5"))
    pieces = _four_pieces()
    fr = frame(1, pieces)
    usable, _ = usable_detections(fr, cfg)
    assert len(usable) == 2
    assert len(fr.detections) == 4, "几何里必须仍然有 4 件（障碍物不能消失）"


def test_skip_all_shapes_yields_empty_usable():
    cfg = build_config(_ini("skip_all", skip_shapes="1,2,3,4,5,6"))
    usable, notes = usable_detections(frame(1, _four_pieces()), cfg)
    assert usable == ()
    assert any("主动放弃" in n for n in notes)


def test_ordering_skips_cylinder_cone():
    cfg = build_config(_ini("skip_35_order", skip_shapes="3,5"))
    ordered = order_by_row_scan(frame(1, _four_pieces()), cfg)
    assert [d.class_id for d in ordered] == [1, 6]


def test_skip_shapes_in_code_mode():
    cfg = build_config(_ini("skip_code_mode", skip_shapes="3,5", class_id_mode="code"))
    pieces = (
        det(1, 1, 10.0, 30.0, class_id=4),    # code 4 = cube 形状1
        det(2, 2, 20.0, 30.0, class_id=13),   # code 13 = 形状3（圆柱）
        det(3, 3, 30.0, 30.0, class_id=23),   # code 23 = 形状5（圆锥）
        det(4, 4, 40.0, 30.0, class_id=28),   # code 28 = 形状6（四面体）
    )
    usable, _ = usable_detections(frame(1, pieces), cfg)
    assert [d.class_id for d in usable] == [4, 28]
