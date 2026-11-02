"""加权评分排序单测（2026-11-02 新增）。

用户口径：「主摄像头前端的最先夹取；最先夹取里面再按置信度高的先（正方体这种好夹的）；
把路线、物料夹取、前端三个都考虑进去」⇒ 加权评分，而不是硬性字典序。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import DEMO_INI, det, frame
from electrical_control.pick_strategy.chain_adapter import make_payload_orderer
from electrical_control.pick_strategy.config import ConfigError, build_config
from electrical_control.pick_strategy.orderer import (
    DEFAULT_WEIGHTS,
    ORDER_MODES,
    SettleTracker,
    apply_hard_first_guard,
    order_by_weighted,
    score_detections,
)


def _ini(name: str, **replaced) -> str:
    """基于 demo ini 生成变体（变体行必须带来源标签，解析器 fail-closed）。"""
    text = Path(DEMO_INI).read_text(encoding="utf-8")
    for key, value in replaced.items():
        old = None
        for line in text.splitlines():
            if line.strip().startswith(key + " "):
                old = line
                break
        assert old is not None, "demo ini 里找不到 %r" % key
        text = text.replace(old, "%s = %s  # 【待实测】测试变体" % (key, value), 1)
    d = Path(__file__).resolve().parent / "_tmp"
    d.mkdir(exist_ok=True)
    out = d / (name + ".ini")
    out.write_text(text, encoding="utf-8")
    return str(out)


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def test_default_weights(demo_config):
    assert (demo_config.weight_front, demo_config.weight_pick,
            demo_config.weight_route, demo_config.weight_isolation) == (
        0.70, 0.15, 0.10, 0.05)


def test_weighted_mode_registered():
    assert "weighted" in ORDER_MODES


def test_weights_parse_from_ini():
    cfg = build_config(_ini("w_custom", weight_front="0.6", weight_pick="0.2",
                            weight_route="0.1", weight_isolation="0.1"))
    assert cfg.weight_front == 0.6
    assert cfg.weight_pick == 0.2
    assert cfg.weight_route == 0.1
    assert cfg.weight_isolation == 0.1


def test_negative_weight_rejected():
    with pytest.raises(ConfigError):
        build_config(_ini("w_neg", weight_front="-0.1"))


def test_zero_sum_weights_rejected():
    with pytest.raises(ConfigError):
        build_config(_ini("w_zero", weight_front="0", weight_pick="0",
                          weight_route="0", weight_isolation="0"))


def test_non_numeric_weight_rejected():
    with pytest.raises(ConfigError):
        build_config(_ini("w_bad", weight_route="abc"))


# --------------------------------------------------------------------------- #
# 分项与总分
# --------------------------------------------------------------------------- #
def test_score_has_all_facets(demo_config):
    fr = frame(1, [det(1, 1, 10.0, 30.0)])
    scores = score_detections(fr, demo_config)
    assert set(scores) == {1}
    assert set(scores[1]) == {"front", "pick", "route", "isolation", "total"}
    for key, val in scores[1].items():
        assert 0.0 <= val <= 1.0 + 1e-9, (key, val)


def test_front_favours_piece_near_open_edge(demo_config):
    """open_side=y_max ⇒ y 越大越靠前（无壁边），加权分应更高。"""
    front_piece = det(1, 1, 0.0, 60.0)     # 靠前
    back_piece = det(2, 1, 0.0, -20.0)     # 靠里
    fr = frame(1, [front_piece, back_piece])
    scores = score_detections(fr, demo_config)
    assert scores[1]["front"] > scores[2]["front"]
    assert scores[1]["total"] > scores[2]["total"]
    ordered = order_by_weighted(fr, demo_config)
    assert [d.target_seq for d in ordered] == [1, 2]


def test_pick_favours_easy_class_when_geometry_equal(demo_config):
    """同位置下：正方体(tier0) 应优先于圆锥(tier2)。"""
    cube = det(1, 1, 0.0, 30.0, class_id=1)
    cone = det(2, 1, 0.5, 30.0, class_id=5)   # 位置几乎相同，front 差异极小
    fr = frame(1, [cube, cone])
    scores = score_detections(fr, demo_config)
    assert scores[1]["pick"] > scores[2]["pick"]
    ordered = order_by_weighted(fr, demo_config)
    assert ordered[0].target_seq == 1, "好夹的先"


def test_route_weight_can_dominate(demo_config):
    """把路线权重拉满：离 HOME 近的先（即使它靠里）。"""
    cfg = build_config(_ini("w_route", weight_front="0", weight_pick="0",
                            weight_route="1", weight_isolation="0"))
    near_home = det(1, 1, 0.0, -20.0)     # 靠里但近 HOME
    far_front = det(2, 1, 0.0, 60.0)      # 靠前但远 HOME
    fr = frame(1, [near_home, far_front])
    scores = score_detections(fr, cfg, weights={"front": 0, "pick": 0,
                                                "route": 1, "isolation": 0})
    assert scores[1]["route"] > scores[2]["route"]
    ordered = order_by_weighted(fr, cfg, weights={"front": 0, "pick": 0,
                                                  "route": 1, "isolation": 0})
    assert ordered[0].target_seq == 1


def test_last_drop_participates_in_route(demo_config):
    """给了上次落点后，路由分应该变化（越靠近落点越高）。"""
    from electrical_control.pick_strategy.geometry import Point

    a = det(1, 1, 0.0, 30.0)
    b = det(2, 1, 40.0, 30.0)
    fr = frame(1, [a, b])
    scores = score_detections(fr, demo_config, last_drop=Point(40.0, 30.0))
    assert scores[2]["route"] > scores[1]["route"]


def test_moving_piece_still_deferred(demo_config):
    """停稳是更高一级条件：还在动的件即使加权分高也排最后。"""
    moving = det(1, 1, 0.0, 60.0)          # 位置最好
    steady = det(2, 1, 0.0, -20.0)         # 位置差
    tracker = SettleTracker(settle_frames=3, settle_shift_mm=4.0)
    for i in range(3):
        tracker.observe(frame(i + 1, [det(1, 1, 30.0 * i, 60.0),
                                      det(2, 1, 0.0, -20.0)]))
    fr = frame(4, [moving, steady])
    ordered = order_by_weighted(fr, demo_config, settle=tracker)
    assert ordered[0].target_seq == 2, "在动的高分件仍然排最后"


def test_ties_are_deterministic(demo_config):
    """同分时按行扫描键定序（可复现）。"""
    a = det(1, 1, -30.0, 30.0)
    b = det(2, 1, 30.0, 30.0)
    fr = frame(1, [a, b])
    first = [d.target_seq for d in order_by_weighted(fr, demo_config)]
    second = [d.target_seq for d in order_by_weighted(fr, demo_config)]
    assert first == second


def test_default_weights_are_referenced(demo_config):
    """默认权重表应被使用（改权重后总分变化）。"""
    fr = frame(1, [det(1, 1, 0.0, 30.0)])
    base = score_detections(fr, demo_config)[1]["total"]
    heavier_front = score_detections(
        fr, demo_config, weights={"front": 1.0, "pick": 0.0,
                                  "route": 0.0, "isolation": 0.0})[1]["total"]
    assert base != heavier_front
    assert DEFAULT_WEIGHTS["front"] == 0.70


# --------------------------------------------------------------------------- #
# 接链（payload 层）
# --------------------------------------------------------------------------- #
class _Payload:
    __slots__ = ("target_seq", "class_id", "pick_x_position", "pick_y_position")

    def __init__(self, seq, class_id, x_mm, y_mm, offset):
        self.target_seq = seq
        self.class_id = class_id
        self.pick_x_position = int(round((x_mm + offset.x_mm) * 10))
        self.pick_y_position = int(round((y_mm + offset.y_mm) * 10))


def test_chain_adapter_weighted_mode_respects_hard_first_guard(demo_config):
    """默认护栏：靠前的圆锥虽是加权第一，但难件不得排首位 ⇒ 正方体先抓。"""
    off = demo_config.tool_offset
    cone_front = _Payload(1, 5, 0.0, 60.0, off)     # 靠前但难夹
    cube_back = _Payload(2, 1, 0.0, 0.0, off)       # 靠里但好夹
    orderer = make_payload_orderer(demo_config, order_mode="weighted")
    out = orderer((cone_front, cube_back))
    assert len(out) == 2
    assert [p.target_seq for p in out] == [2, 1], "难件不得排首位"


def test_hard_first_guard_can_be_disabled_via_config():
    """关掉护栏后回到纯加权顺序（圆锥在前）。"""
    cfg = build_config(_ini("no_guard", weighted_guard_hard_first="false"))
    off = cfg.tool_offset
    cone_front = _Payload(1, 5, 0.0, 60.0, off)
    cube_back = _Payload(2, 1, 0.0, 0.0, off)
    orderer = make_payload_orderer(cfg, order_mode="weighted")
    assert [p.target_seq for p in orderer((cone_front, cube_back))] == [1, 2]


# --------------------------------------------------------------------------- #
# 难件不得排首位护栏（2026-11-02 测评结论）
# --------------------------------------------------------------------------- #
def test_guard_moves_hard_piece_out_of_first_place(demo_config):
    cone = det(1, 5, 0.0, 60.0, class_id=5)      # 位置最好但难夹
    cube = det(2, 1, 0.0, -20.0, class_id=1)
    fr = frame(1, [cone, cube])
    guarded = order_by_weighted(fr, demo_config)
    assert guarded[0].class_id == 1, "护栏后首件必须是易件"


def test_guard_disabled_keeps_weighted_order(demo_config):
    cone = det(1, 5, 0.0, 60.0, class_id=5)
    cube = det(2, 1, 0.0, -20.0, class_id=1)
    fr = frame(1, [cone, cube])
    raw = order_by_weighted(fr, demo_config, guard_hard_first=False)
    assert raw[0].class_id == 5


def test_guard_noop_when_first_is_easy(demo_config):
    a = det(1, 1, 0.0, 60.0, class_id=1)
    b = det(2, 3, 0.0, -20.0, class_id=3)
    fr = frame(1, [a, b])
    ordered = order_by_weighted(fr, demo_config)
    assert ordered[0].class_id == 1


def test_guard_noop_when_all_pieces_are_hard(demo_config):
    cylinder = det(1, 3, 0.0, 60.0, class_id=3)
    cone = det(2, 5, 0.0, -20.0, class_id=5)
    fr = frame(1, [cylinder, cone])
    ordered = order_by_weighted(fr, demo_config)
    assert len(ordered) == 2                      # 全难件：保持原样，不崩


def test_apply_guard_helper_swaps_first_easy():
    easy = det(9, 1, 0.0, 0.0, class_id=1)
    hard = det(8, 5, 0.0, 0.0, class_id=5)
    out = apply_hard_first_guard((hard, easy))
    assert out[0].class_id == 1 and out[1].class_id == 5


def test_chain_adapter_weighted_falls_back_on_bad_payload(demo_config):
    """缺抓取点的件不参与排序但也必须不丢。"""
    orderer = make_payload_orderer(demo_config, order_mode="weighted")

    class _Broken:
        target_seq = 9
        class_id = 1

    out = orderer((_Broken(),))
    assert len(out) == 1
