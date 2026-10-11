"""目标选择：无壁边优先级、并列定序、最近件不可行的处理（需求三）。"""

from __future__ import annotations

from conftest import det, frame

from electrical_control.pick_strategy import (
    Refusal,
    RefusalCode,
    describe_selection_limitation,
    order_by_open_edge,
    select_target,
)


def test_nearest_to_open_edge_wins_over_nearest_to_home(demo_config):
    """规则三.1：优先看"到无壁边的距离"，**不是**到夹爪当前位置的距离。

    演示托盘无壁边 = y_max = +62.5；HOME 记账 (−95,−97.5) ⇒ 夹爪物理起点 (25.5,−54)。
    far_from_home 在 (30,55)，close_to_home 在 (30,−40)：
      到无壁边：10.0 vs 102.5 → far_from_home 更近
      到起点  ：hypot(4.5,109)=109.1 vs hypot(4.5,14)=14.7 → close_to_home 更近
    若按"离夹爪当前位置最近"排序会选 close_to_home —— 本用例锁死必须是前者。
    """
    fr = frame(1, [det(1, 3, 30.0, -40.0), det(2, 6, 30.0, 55.0)])
    picked = select_target(fr, demo_config)
    assert not isinstance(picked, Refusal)
    assert picked.detection.target_seq == 2
    assert picked.distance_to_open_edge_mm == 7.5  # 62.5 - 55.0


def test_tie_break_uses_empty_travel_then_target_seq(demo_config):
    """规则三.4：距离相同时用（空爪移动距离, target_seq）定序。"""
    # 两件到无壁边都是 32.5mm；seq=2 在 x=30（离起点更近），seq=1 在 x=70
    fr = frame(1, [det(1, 3, 70.0, 30.0), det(2, 6, 30.0, 30.0)])
    picked = select_target(fr, demo_config)
    assert not isinstance(picked, Refusal)
    assert picked.distance_to_open_edge_mm == 32.5
    assert picked.detection.target_seq == 2, "并列时应选空爪移动距离更短的那件"

    # 全部并列（含空爪距离）时按 target_seq 升序
    fr2 = frame(2, [det(9, 3, 30.0, 30.0), det(4, 6, 30.0, 30.0)])
    assert select_target(fr2, demo_config).detection.target_seq == 4


def test_order_by_open_edge_is_strictly_sorted(demo_config):
    fr = frame(1, [det(1, 3, 30.0, -40.0), det(2, 6, 30.0, 55.0),
                   det(3, 6, 30.0, 20.0)])
    ordered = order_by_open_edge(fr, demo_config)
    assert [d.target_seq for d in ordered] == [2, 3, 1]


def test_unreachable_nearest_is_refused_without_falling_back(demo_config):
    """规则三.7：最近件抓不到 → 拒识本件，**不得**改抓更远的件。"""
    # (10,55) 到无壁边 7.5mm（最近），但 X=10 < 可抓窗口下界 25.5
    # (55,10) 到无壁边 52.5mm，本身是可以抓的
    fr = frame(1, [det(1, 3, 10.0, 55.0), det(2, 6, 55.0, 10.0)])
    picked = select_target(fr, demo_config)
    assert isinstance(picked, Refusal)
    assert picked.code == RefusalCode.OUT_OF_REACH_WINDOW
    assert "不" in picked.detail  # 明确写出"不改为抓更远的件"


def test_object_window_is_derived_from_tool_offset_and_workspace(demo_config):
    """可抓窗口 = 可达域 − ToolOffset；用文档里的数值交叉验证。"""
    window = demo_config.object_window
    assert (window.x_min, window.x_max) == (25.5, 210.5)
    assert (window.y_min, window.y_max) == (-54.0, 136.0)


def test_detection_without_box_id_is_not_a_candidate(demo_config):
    fr = frame(1, [det(1, None, 30.0, 60.0), det(2, 6, 30.0, 20.0)])
    picked = select_target(fr, demo_config)
    assert not isinstance(picked, Refusal)
    assert picked.detection.target_seq == 2, "无 box_id 的件不能被选为抓取目标"
    assert picked.candidate_count == 1


def test_no_usable_target_is_refused(demo_config):
    picked = select_target(frame(1, [det(1, None, 30.0, 30.0)]), demo_config)
    assert isinstance(picked, Refusal)
    assert picked.code == RefusalCode.NO_USABLE_TARGET


def test_center_mode_declares_its_limitation(demo_config):
    """规则三.4：现有接口只有中心坐标时必须说明局限，不得假装是轮廓距离。"""
    text = describe_selection_limitation(demo_config.selection_mode)
    assert "中心" in text and "轮廓" in text and "bbox" in text
