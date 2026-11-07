"""360° 转盘到位守卫（位置域，2026-11-07）。

只测纯逻辑：FakeBackend 的 `read_pos()` 可编程 + 假时钟，**不依赖现场实测值**。
"""

from __future__ import annotations

import pytest

from electrical_control.rpi.turntable import (
    FakeBackend,
    Turntable,
    TurntableConfig,
    TurntableLocked,
    TurntableUncalibrated,
)
from electrical_control.rpi.turntable_position_guard import (
    ArrivalConfig,
    PositionTurnGuard,
    counts_delta,
)

POS6 = {1: 2048, 2: 1365, 3: 683, 4: 0, 5: 3413, 6: 2731}


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _mk(
    pos_table: dict[int, int] | None = None,
    *,
    tolerance: int = 20,
    timeout_s: float = 2.0,
):
    cfg = TurntableConfig(
        zero_pulse_us=1500,
        us_per_degree=655.0 / 90.0,
        angle_sign=-1,
        pos_table=dict(POS6 if pos_table is None else pos_table),
        settle_s=0.0,
    )
    backend = FakeBackend()
    tt = Turntable(cfg, backend)
    clock = FakeClock()
    guard = PositionTurnGuard(
        tt,
        ArrivalConfig(tolerance_counts=tolerance, timeout_s=timeout_s, poll_s=0.0),
        clock=clock,
    )
    return guard, tt, backend, clock


class _NoReadBackend:
    """只有脉宽接口的后端：位置域守卫必须拒绝开工（fail-closed）。"""

    def set_pulse_us(self, pulse_us: int) -> None:
        pass

    def close(self) -> None:
        pass


def test_counts_delta_is_circular():
    assert counts_delta(100, 110) == 10
    assert counts_delta(110, 100) == 10
    assert counts_delta(0, 2048) == 2048
    assert counts_delta(15, 4095) == 16   # 环绕：只差 16，不是 4080
    assert counts_delta(4095, 0) == 1


def test_preflight_requires_read_pos():
    cfg = TurntableConfig(zero_pulse_us=1500, us_per_degree=655 / 90, angle_sign=-1,
                          pos_table=dict(POS6))
    tt = Turntable(cfg, _NoReadBackend())
    guard = PositionTurnGuard(tt)
    with pytest.raises(Exception):
        guard.preflight()


def test_preflight_ok_with_fake_backend():
    guard, _tt, _be, _clock = _mk()
    guard.preflight()   # 不抛即通过


def test_arrival_within_tolerance_clears_pending():
    guard, tt, be, clock = _mk()
    assert guard.before_dispatch(1) is None
    assert be.positions == [2048]
    # 下发后 FakeBackend 的读回就是目标（模拟"已在该位置"）⇒ 派发时即判到位
    assert guard.arrived == 1
    assert guard.poll() is None
    assert guard.turns == 1
    assert guard.failed is None


def test_repeat_same_box_is_immediately_arrived():
    guard, _tt, be, _clock = _mk()
    guard.before_dispatch(2)
    guard.before_dispatch(2)          # 重复派同一格
    assert guard.arrived == 2
    assert guard.failed is None


def test_deviation_within_tolerance_passes():
    guard, tt, be, clock = _mk()
    be.read_fail = True               # 先构造出"待确认"状态
    guard.before_dispatch(3)          # 目标 683
    be.read_fail = False
    be.position = 683 + 5             # 偏差 5 ≤ 20
    assert guard.poll() is None
    assert guard.arrived == 1
    assert guard.failed is None


def test_deviation_100_fails_and_locks_after_timeout():
    guard, tt, be, clock = _mk()
    be.read_fail = True
    guard.before_dispatch(3)          # 目标 683：派发时读不到 ⇒ 进入待确认
    be.read_fail = False
    be.position = 783                 # 偏差 100 > 20：未到位
    assert guard.poll() is None, "未到超时前只是继续等，不能误判"
    clock.advance(2.1)
    reason = guard.poll()
    assert reason is not None and "到位超时" in reason
    assert guard.failed is not None
    # 锁是持久的：再派件直接被拒
    assert guard.before_dispatch(1) == guard.failed
    with pytest.raises(TurntableLocked):
        tt.command_box_position(1)


def test_read_none_fails_at_timeout():
    guard, tt, be, clock = _mk()
    be.read_fail = True
    guard.before_dispatch(2)          # 目标 1365：派发时就读不到
    assert guard.poll() is None
    clock.advance(2.1)
    reason = guard.poll()
    assert reason is not None and "读不到" in reason
    assert tt._locked is True


def test_motion_done_before_arrival_fails():
    guard, tt, be, _clock = _mk()
    be.read_fail = True
    guard.before_dispatch(4)
    guard.note_motion_done()
    assert guard.failed is not None and "MOTION_DONE" in guard.failed
    assert guard.unverified_at_motion_done == 1
    assert tt._locked is True


def test_motion_done_after_arrival_is_fine():
    guard, _tt, _be, _clock = _mk()
    guard.before_dispatch(4)          # FakeBackend 读回=目标 ⇒ 立即到位
    guard.note_motion_done()
    assert guard.failed is None
    assert guard.unverified_at_motion_done == 0


def test_wrap_around_position_counts_as_arrived():
    guard, _tt, be, _clock = _mk(pos_table={1: 15, 2: 0, 3: 2048, 4: 1000, 5: 3000, 6: 4000})
    guard.before_dispatch(1)          # 目标 15
    be.position = 4095                # 环形差 = 16 ≤ 20
    assert guard.poll() is None


def test_unknown_box_raises_fail_closed():
    guard, _tt, _be, _clock = _mk()
    with pytest.raises(TurntableUncalibrated):
        guard.before_dispatch(9)
