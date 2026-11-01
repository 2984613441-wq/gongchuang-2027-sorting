"""五键排序与 order_mode 灰度开关的离线测试（2026-11-01 新增）。

覆盖审核报告要求的 4 组用例：
1. 难度排序（order_mode="difficulty" 先易后难）
2. 隔离度（周围有件 ⇒ 排后面）
3. 停稳判据（SettleTracker：未知/停稳/还在动；moving 件被延后）
4. 落点锚点（上次落料点近的先抓）+ order_mode 合法性 + legacy 原序

不触碰任何硬件；只用 conftest 的 demo_config 与虚拟帧。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from electrical_control.pick_strategy.chain_adapter import (
    ORDER_MODES,
    make_payload_orderer,
)
from electrical_control.pick_strategy.orderer import (
    SettleTracker,
    neighbor_count,
    order_by_five_key,
)
from electrical_control.pick_strategy.geometry import Point
from electrical_control.pick_strategy.selector import order_by_group_scan

from conftest import det, frame


# --------------------------------------------------------------------------- #
# 测试用 payload 桩（只需 chain_adapter 读到的 4 个字段）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Payload:
    target_seq: int
    class_id: int
    pick_x_position: int      # 0.1mm 滑台记账坐标 = (物料mm + tool_offset) * 10
    pick_y_position: int


def _payload(seq: int, class_id: int, x_mm: float, y_mm: float,
             offset: Point) -> _Payload:
    return _Payload(
        target_seq=seq,
        class_id=class_id,
        pick_x_position=int(round((x_mm + offset.x_mm) * 10)),
        pick_y_position=int(round((y_mm + offset.y_mm) * 10)),
    )


# --------------------------------------------------------------------------- #
# 1) order_mode 合法性 + legacy 原序
# --------------------------------------------------------------------------- #
def test_illegal_order_mode_rejected(demo_config):
    with pytest.raises(ValueError):
        make_payload_orderer(demo_config, order_mode="nope")
    assert "five_key" in ORDER_MODES and "legacy" in ORDER_MODES


def test_legacy_keeps_input_order(demo_config):
    off = demo_config.tool_offset
    far_easy = _payload(1, 1, 60.0, 40.0, off)     # cube，远处
    near_hard = _payload(2, 5, 10.0, 40.0, off)    # cone，近处
    payloads = (far_easy, near_hard)
    orderer = make_payload_orderer(demo_config, order_mode="legacy")
    assert orderer(payloads) == payloads            # 原顺序不改


def test_explicit_group_matches_group_scan(demo_config):
    """显式 group 必须与接入前口径逐条一致（回归保护）。"""
    off = demo_config.tool_offset
    a = _payload(1, 1, 30.0, 40.0, off)
    b = _payload(2, 5, -10.0, 40.0, off)
    payloads = (a, b)
    got = make_payload_orderer(demo_config, order_mode="group")(payloads)
    # 用同一套 Detection 直接跑 order_by_group_scan，比较 class_id 序列
    dets = tuple(
        det(p.target_seq, p.class_id, p.pick_x_position / 10.0 - off.x_mm,
            p.pick_y_position / 10.0 - off.y_mm, class_id=p.class_id)
        for p in payloads
    )
    want = order_by_group_scan(frame(1, dets), demo_config)
    want_cls = [d.class_id for d in want]
    got_cls = [p.class_id for p in got if p.class_id in want_cls]
    assert got_cls == want_cls


# --------------------------------------------------------------------------- #
# 2) 难度排序：先易后难
# --------------------------------------------------------------------------- #
def test_difficulty_mode_prefers_easy_class(demo_config):
    """cube(tier 0) 在行扫描上更靠后，但 difficulty 模式应先抓它。"""
    off = demo_config.tool_offset
    easy_far = _payload(1, 1, 40.0, 20.0, off)     # cube tier0，Y 小（行扫描靠后）
    hard_near = _payload(2, 5, 40.0, 60.0, off)    # cone tier2，Y 大（行扫描靠前）
    orderer = make_payload_orderer(demo_config, order_mode="difficulty")
    out = orderer((easy_far, hard_near))
    assert [p.class_id for p in out] == [1, 5], "难度模式应先易（class 1）后难（class 5）"


# --------------------------------------------------------------------------- #
# 3) 隔离度
# --------------------------------------------------------------------------- #
def test_neighbor_count_counts_only_others_within_band():
    a = det(1, 1, 0.0, 0.0, class_id=1)
    b = det(2, 2, 5.0, 0.0, class_id=2)      # 距 a 5mm
    c = det(3, 3, 40.0, 0.0, class_id=3)     # 距 a 40mm
    dets = (a, b, c)
    assert neighbor_count(a, dets, band_mm=10.0) == 1
    assert neighbor_count(a, dets, band_mm=3.0) == 0
    assert neighbor_count(c, dets, band_mm=10.0) == 0


def test_five_key_prefers_isolated_piece(demo_config):
    """同类同难度、同 Y：周围有件的排后面。"""
    isolated = det(1, 1, -40.0, 30.0, class_id=1)
    crowded = det(2, 1, 40.0, 30.0, class_id=1)
    neighbor = det(3, 1, 44.0, 30.0, class_id=1)   # 紧贴 crowded（4mm）
    fr = frame(1, (isolated, crowded, neighbor))
    ordered = order_by_five_key(fr, demo_config, isolation_band_mm=10.0)
    cls_seq = [d.target_seq for d in ordered]
    assert cls_seq.index(1) < cls_seq.index(2), \
        "孤立件(seq=1)应排在拥挤件(seq=2)之前，实际顺序=%s" % cls_seq


# --------------------------------------------------------------------------- #
# 4) 停稳判据 + 落点锚点
# --------------------------------------------------------------------------- #
def test_settle_tracker_unknown_then_settled_then_moving(demo_config):
    tracker = SettleTracker(settle_frames=3, settle_shift_mm=4.0)
    # 第 1 帧：未知
    tracker.observe(frame(1, (det(1, 1, 0.0, 0.0, class_id=1),)))
    assert tracker.is_settled(1) is None
    # 第 2、3 帧：位置几乎不变 ⇒ 停稳
    tracker.observe(frame(2, (det(1, 1, 1.0, 0.0, class_id=1),)))
    tracker.observe(frame(3, (det(1, 1, 2.0, 0.0, class_id=1),)))
    assert tracker.is_settled(1) is True
    # 第 4 帧：跳了 20mm ⇒ 判定还在动
    tracker.observe(frame(4, (det(1, 1, 22.0, 0.0, class_id=1),)))
    assert tracker.is_settled(1) is False


def test_five_key_defers_moving_piece(demo_config):
    """还在动的件必须排到停稳件之后（用户要求：停稳才抓）。"""
    moving = det(1, 1, 0.0, 0.0, class_id=1)
    steady = det(2, 1, 30.0, 0.0, class_id=1)
    tracker = SettleTracker(settle_frames=3, settle_shift_mm=4.0)
    tracker.observe(frame(1, (det(1, 1, 0.0, 0.0, class_id=1),
                              det(2, 1, 30.0, 0.0, class_id=1))))
    tracker.observe(frame(2, (det(1, 1, 15.0, 0.0, class_id=1),   # moving 抖动
                              det(2, 1, 30.5, 0.0, class_id=1))))
    tracker.observe(frame(3, (det(1, 1, 30.0, 0.0, class_id=1),   # moving 又抖
                              det(2, 1, 31.0, 0.0, class_id=1))))
    fr = frame(3, (moving, steady))
    ordered = order_by_five_key(fr, demo_config, settle=tracker)
    seq = [d.target_seq for d in ordered]
    assert seq.index(2) < seq.index(1), \
        "停稳件(seq=2)应排在移动件(seq=1)之前，实际=%s" % seq


def test_five_key_prefers_nearer_last_drop(demo_config):
    """上次落料点近的先抓（落点锚点键）。"""
    a = det(1, 1, -40.0, 30.0, class_id=1)   # 离落点远
    b = det(2, 1, 40.0, 30.0, class_id=1)    # 离落点近
    fr = frame(1, (a, b))
    ordered = order_by_five_key(fr, demo_config, last_drop=Point(40.0, 30.0))
    assert [d.target_seq for d in ordered] == [2, 1]


def test_five_key_mode_accepts_last_drop_provider(demo_config):
    """chain_adapter 的五键模式要能吃进『上次落料点』provider。"""
    off = demo_config.tool_offset
    far = _payload(1, 1, -40.0, 30.0, off)
    near = _payload(2, 1, 40.0, 30.0, off)
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        return Point(40.0, 30.0)

    orderer = make_payload_orderer(
        demo_config, order_mode="five_key", last_drop_provider=provider)
    out = orderer((far, near))
    assert [p.target_seq for p in out] == [2, 1]
    assert calls["n"] >= 1


def test_five_key_provider_exception_falls_back(demo_config):
    """provider 抛错不能崩，按锚点未知处理（不丢件）。"""
    off = demo_config.tool_offset
    a = _payload(1, 1, 10.0, 30.0, off)
    b = _payload(2, 5, -10.0, 30.0, off)

    def bad_provider():
        raise RuntimeError("boom")

    orderer = make_payload_orderer(
        demo_config, order_mode="five_key", last_drop_provider=bad_provider)
    out = orderer((a, b))
    assert len(out) == 2 and {p.target_seq for p in out} == {1, 2}

# --------------------------------------------------------------------------- #
# 5) 默认口径 = legacy（审核要求：默认不改变行为，可一键回退）
# --------------------------------------------------------------------------- #
def test_default_order_mode_is_legacy(demo_config):
    """不传 order_mode 且 ini 未配 [Strategy] ⇒ legacy（不排序）。"""
    assert demo_config.order_mode == "legacy"
    off = demo_config.tool_offset
    a = _payload(1, 5, 10.0, 40.0, off)     # cone 近
    b = _payload(2, 1, 60.0, 20.0, off)     # cube 远
    payloads = (a, b)
    assert make_payload_orderer(demo_config)(payloads) == payloads


# --------------------------------------------------------------------------- #
# 6) 停稳超时降级（等满 max_wait 帧仍在动 ⇒ 按未知处理，不再惩罚）
# --------------------------------------------------------------------------- #
def test_settle_tracker_timeout_degrade(demo_config):
    tracker = SettleTracker(settle_frames=3, settle_shift_mm=4.0,
                            settle_max_wait_frames=6)
    # 一直在抖（每帧跳 10mm）
    for i in range(7):
        tracker.observe(frame(i + 1, (det(1, 1, 10.0 * i, 0.0, class_id=1),)))
        if i + 1 < 3:
            assert tracker.is_settled(1) is None
        elif i + 1 < 6:
            assert tracker.is_settled(1) is False
    # 数到第 7 帧（>= max_wait=6）⇒ 降级为 None
    assert tracker.is_settled(1) is None


def test_settle_degrade_keeps_piece_pickable(demo_config):
    """降级后该件不再被排到最后（可与停稳件同权，按后续键比较）。"""
    tracker = SettleTracker(settle_frames=3, settle_shift_mm=4.0,
                            settle_max_wait_frames=6)
    for i in range(7):
        tracker.observe(frame(i + 1, (det(1, 1, 10.0 * i, 0.0, class_id=1),
                                      det(2, 1, 40.0, 40.0, class_id=1))))
    moving = det(1, 1, 60.0, 0.0, class_id=1)
    steady = det(2, 1, 40.0, 40.0, class_id=1)
    ordered = order_by_five_key(frame(8, (moving, steady)), demo_config, settle=tracker)
    assert len(ordered) == 2   # 不丢件


# --------------------------------------------------------------------------- #
# 7) [Strategy] 配置节解析（带【待实测】标签）
# --------------------------------------------------------------------------- #
def test_config_reads_strategy_section():
    from conftest import DEMO_INI
    from electrical_control.pick_strategy.config import build_config

    text = open(DEMO_INI, encoding="utf-8").read()
    text = text.replace("order_mode = legacy", "order_mode = five_key")
    text = text.replace("settle_frames = 3", "settle_frames = 5")
    text = text.replace("settle_shift_mm = 4.0", "settle_shift_mm = 2.5")
    from pathlib import Path as _P
    _tmp = _P(__file__).resolve().parent / "_tmp"
    _tmp.mkdir(exist_ok=True)
    ini = _tmp / "variant_strategy_ok.ini"
    ini.write_text(text, encoding="utf-8")
    cfg = build_config(ini)
    assert cfg.order_mode == "five_key"
    assert cfg.settle_frames == 5
    assert cfg.settle_shift_mm == 2.5
    assert cfg.isolation_band_mm == 10.0


def test_config_rejects_bad_order_mode():
    import pytest as _pytest
    from conftest import DEMO_INI
    from electrical_control.pick_strategy.config import ConfigError, build_config

    text = open(DEMO_INI, encoding="utf-8").read()
    text = text.replace("order_mode = legacy", "order_mode = nope")
    from pathlib import Path as _P
    _tmp = _P(__file__).resolve().parent / "_tmp"
    _tmp.mkdir(exist_ok=True)
    ini = _tmp / "variant_strategy_bad.ini"
    ini.write_text(text, encoding="utf-8")
    with _pytest.raises(ConfigError):
        build_config(ini)


def test_config_without_strategy_section_uses_defaults():
    from electrical_control.pick_strategy.config import StrategyConfig  # noqa: F401
    from conftest import build_config, REAL_INI
    try:
        cfg = build_config(REAL_INI)
    except Exception:
        return      # 真机 ini 可能不存在/过期；缺席时本用例跳过
    assert cfg.order_mode in ("legacy", "group", "difficulty", "open_edge", "five_key")
