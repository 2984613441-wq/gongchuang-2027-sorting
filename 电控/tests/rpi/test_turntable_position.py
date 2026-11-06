"""位置域 API（2026-11-07，S1 转盘接线的一部分）。

背景：360° 分度下货格角度可到 ±180°，而脉宽域只有 [500,2500]µs（≈±137°）
⇒ 必须有一条只走位置值（0~4095）的通路，不能借道脉宽。

本文件只测**纯逻辑**（FakeBackend），不连硬件、不碰串口、不发光。
"""

from __future__ import annotations

import pytest

from electrical_control.rpi.turntable import (
    POS_MAX,
    POS_MIN,
    FakeBackend,
    Turntable,
    TurntableConfig,
    TurntableLocked,
    TurntableUncalibrated,
)

US_PER_DEG = 655.0 / 90.0
# 360° 分度示例：6 格 × 60°，±150° 覆盖整圈（旧 ±112.5° 只覆盖 270°）
ANGLES_360 = {1: -150.0, 2: -90.0, 3: -30.0, 4: 30.0, 5: 90.0, 6: 150.0}
# 旧 270° 分度示例（脉宽域内，用于兼容性回归）
ANGLES_270 = {i + 1: -112.5 + 45.0 * i for i in range(6)}


def _cfg(angles: dict[int, float] | None = None, **kw) -> TurntableConfig:
    base = dict(
        zero_pulse_us=1500,
        us_per_degree=US_PER_DEG,
        angle_sign=-1,
        angle_table=ANGLES_270 if angles is None else angles,
        settle_s=0.0,
    )
    base.update(kw)
    return TurntableConfig(**base)


class _PulseOnlyBackend:
    """只有脉宽接口的旧后端（模拟 PwFileBackend / PigpioBackend）。"""

    def __init__(self) -> None:
        self.pulses: list[int] = []

    def set_pulse_us(self, pulse_us: int) -> None:
        self.pulses.append(int(pulse_us))

    def close(self) -> None:
        return


def test_pos_for_angle_covers_full_360_inside_range():
    cfg = _cfg(ANGLES_360)
    positions = [cfg.pos_for_angle(a) for a in ANGLES_360.values()]
    assert all(POS_MIN <= p <= POS_MAX for p in positions), positions
    # sign=-1 ⇒ 角度增大，位置减小（单调）
    assert positions == sorted(positions, reverse=True), positions


def test_pos_for_box_uses_angle_table():
    cfg = _cfg(ANGLES_360)
    for box, angle in ANGLES_360.items():
        assert cfg.pos_for_box(box) == cfg.pos_for_angle(angle)


def test_pos_for_angle_out_of_range_fail_closed():
    cfg = _cfg(ANGLES_360)
    with pytest.raises(TurntableUncalibrated):
        cfg.pos_for_angle(400.0)


def test_pos_for_box_unknown_box_rejected():
    cfg = _cfg(ANGLES_360)
    with pytest.raises(TurntableUncalibrated):
        cfg.pos_for_box(9)


def test_pulse_and_position_domains_are_consistent():
    """同一角度两条换算必须落在同一条直线上（位置→脉宽可逆）。"""
    cfg = _cfg()
    for angle in (-112.5, -45.0, 0.0, 45.0, 112.5):
        pos = cfg.pos_for_angle(angle)
        assert cfg.pulse_for_position(pos) == cfg.pulse_for_angle(angle)


def test_position_coverage_matches_table():
    cfg = _cfg(ANGLES_360)
    lo, hi = cfg.position_coverage()
    expected = sorted(cfg.pos_for_angle(a) for a in ANGLES_360.values())
    assert (lo, hi) == (expected[0], expected[-1])


def test_command_box_position_records_via_backend():
    be = FakeBackend()
    tt = Turntable(_cfg(ANGLES_360), be)
    pos = tt.command_box_position(3)
    assert pos == _cfg(ANGLES_360).pos_for_box(3)
    assert be.positions == [pos]
    assert be.pulses == [], "位置域动作不得退化成脉宽动作"
    assert tt.current_box == 3


def test_goto_box_position_returns_target_and_keeps_backend_in_sync():
    be = FakeBackend()
    tt = Turntable(_cfg(ANGLES_360), be)
    pos = tt.goto_box_position(5)
    assert be.positions == [pos]
    assert be.read_pos() == pos, "FakeBackend 读回应与下发一致（供到位守卫测试用）"


def test_goto_position_validates_range():
    tt = Turntable(_cfg(ANGLES_360), FakeBackend())
    with pytest.raises(TurntableUncalibrated):
        tt.goto_position(POS_MAX + 1)
    with pytest.raises(TurntableUncalibrated):
        tt.goto_position(POS_MIN - 1)


def test_locked_turntable_rejects_position_actions():
    tt = Turntable(_cfg(ANGLES_360), FakeBackend())
    tt.lock("单测：强制锁定")
    with pytest.raises(TurntableLocked):
        tt.command_box_position(1)
    with pytest.raises(TurntableLocked):
        tt.goto_position(2048)


def test_pulse_only_backend_rejects_360_degree_action():
    """旧脉宽后端 + 360° 角度表 ⇒ fail-closed，而不是静默 clamp 到 190/2810µs。"""
    be = _PulseOnlyBackend()
    tt = Turntable(_cfg(ANGLES_360), be)
    with pytest.raises(TurntableUncalibrated):
        tt.command_box_position(1)   # -150° ⇒ 位置 3755 ⇒ 脉宽越界
    assert be.pulses == []


def test_fake_backend_read_pos_can_simulate_failure():
    be = FakeBackend()
    assert be.read_pos() == 2048
    be.read_fail = True
    assert be.read_pos() is None
