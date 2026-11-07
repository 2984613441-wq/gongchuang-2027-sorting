"""360° 转盘「转没转到位」的运行守卫（方案B 专用，2026-11-07）。

边界声明（先写权力）
--------------------
本模块**只管时序与校验**，不管：

* 落料点坐标 —— 在 `drop_strategy`（[TurntableAngles] turntable_drop_point）；
* 位置/角度换算与越界拦截 —— 在 `turntable.TurntableConfig` / `Turntable`；
* 串口读写 —— 在 `turntable.SerialServoBackend`（本模块只调 `read_pos()`）。

**不写文件、不碰 GPIO、不碰固件。** 唯一的硬件动作是「经 Turntable 下发目标位置」和
「读回当前位置」，两者都由调用方已经实例化的 `Turntable` 完成。

为什么不用方案C 的 GPIO17 索引
------------------------------
方案C 是「2 个位置（A/B 侧）」⇒ 一个索引开关就够判。360° 是「6 个绝对位置」⇒ 索引
开关无法区分 6 格。ST-3215 是总线舵机，`read_pos()`（寄存器 0x38）直接给出 0~4095 的
当前位置 ⇒ **用读回值判到位**（设计口径 L54：与目标差 ≤ 20 counts ≈ 1.8°）。

失败即锁死
----------
超时 / 读不到 / 落料（MOTION_DONE）时仍未确认 ⇒ 记 ERROR + `turntable.lock()` +
返回原因让调用方**停链**（fail-closed：绝不带着未确认的转盘位置落料）。

⚠️ 读回判据不证明「件真的进了那一格」——那要靠落料位复看（[PlaceEye]，默认关）。
本模块只证明「转盘确实转到了目标位置」。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from electrical_control.rpi.turntable import POS_MAX, Turntable, TurntableError

logger = logging.getLogger(__name__)

# 360° 一圈 = 4096 counts。
COUNTS_PER_TURN = POS_MAX + 1


class _PositionReadable(Protocol):
    def read_pos(self) -> int | None: ...


@dataclass(frozen=True)
class ArrivalConfig:
    """到位判据参数（全部可现场覆盖，默认值来自设计口径）。"""

    tolerance_counts: int = 20      # ≈ 1.8°（360°/4096×20）
    timeout_s: float = 2.5          # ST-3215 默认 move_ms=1500，留余量
    poll_s: float = 0.05            # 读串口的节流间隔（主循环每轮调用也要受控）

    def __post_init__(self) -> None:
        if self.tolerance_counts < 0:
            raise ValueError("tolerance_counts 不能为负")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s 必须 > 0")
        if self.poll_s < 0:
            raise ValueError("poll_s 不能为负")


def counts_delta(a: int, b: int) -> int:
    """两位置值的最短环形距离（0~2048）。转盘是环，0 与 4095 只差 1。"""
    d = abs(int(a) - int(b)) % COUNTS_PER_TURN
    return min(d, COUNTS_PER_TURN - d)


class PositionTurnGuard:
    """一件一转的位置域时序记账。**单线程使用**（主循环里同步调用）。"""

    def __init__(
        self,
        turntable: Turntable,
        config: ArrivalConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.turntable = turntable
        self.config = config or ArrivalConfig()
        self._clock = clock

        self._target: int | None = None     # 本件目标位置（None = 无需校验）
        self._box: int | None = None
        self._issued_at = 0.0
        self._deadline = 0.0
        self._last_read_at = 0.0
        self._last_read: int | None = None
        self._failed: str | None = None

        # 诊断计数（只读，给日志/复盘用）
        self.turns = 0
        self.arrived = 0
        self.unverified_at_motion_done = 0

    # ---- 开工前 ----

    def preflight(self) -> None:
        """开工前确认「读回位置」这条通路是活的；失败即 raise（调用方拒绝开轮）。

        不驱动转盘（与方案C 的 preflight 不同）：位置域没有"侧"要对齐，开工摆位由
        `turntable.goto_zero()` 负责（run_chain 里在 preflight 之前调用）。
        """
        reader = getattr(self.turntable.backend, "read_pos", None)
        if not callable(reader):
            raise TurntableError(
                "转盘后端不支持读回位置（read_pos）：360° 到位校验无法进行，拒绝开轮。"
                "后端=%s。" % type(self.turntable.backend).__name__
            )
        pos = reader()
        if pos is None:
            raise TurntableError(
                "转盘开工自检失败：read_pos() 读不到位置（检查 UART2/供电/舵机 ID）"
            )
        logger.info("转盘开工自检通过：读回位置 %d（容差 ±%d counts，超时 %.1fs）",
                    pos, self.config.tolerance_counts, self.config.timeout_s)

    # ---- 每件 ----

    def before_dispatch(self, box_id: int) -> str | None:
        """**发 ITEM_TASK 之前**调用。返回 None = 可以派件；否则 = 拒做原因（要停链）。"""
        if self._failed is not None:
            return self._failed
        target = self.turntable.command_box_position(box_id)   # 越界/锁定 ⇒ 抛
        now = self._clock()
        self._target = int(target)
        self._box = int(box_id)
        self._issued_at = now
        self._deadline = now + self.config.timeout_s
        self._last_read_at = now
        self._last_read = None
        self.turns += 1

        # 已经在该位置（重复派同一格 / 位置舵机本来就在目标）⇒ 立即算到位，
        # 不必等下一轮 poll，更不该在 MOTION_DONE 时被误判成"未确认"。
        reader = getattr(self.turntable.backend, "read_pos", None)
        pos = reader() if callable(reader) else None
        self._last_read = pos
        if pos is not None and counts_delta(pos, target) <= self.config.tolerance_counts:
            self._target = None
            self.arrived += 1
            logger.info("转盘已在该位置：货格 %d（位置 %d，读回 %d）", box_id, target, pos)
            return None

        logger.info("转盘 → 货格 %d（位置 %d）。**不等整定**，与滑台运动并行。",
                    box_id, target)
        return None

    def poll(self) -> str | None:
        """主循环每轮调用（按 poll_s 节流读串口）。返回非 None 时链路必须停。"""
        if self._failed is not None:
            return self._failed
        if self._target is None:
            return None

        now = self._clock()
        if self._last_read_at and (now - self._last_read_at) < self.config.poll_s:
            return None                      # 节流：主循环转得再快也不刷串口
        self._last_read_at = now

        read = getattr(self.turntable.backend, "read_pos", None)
        pos = read() if callable(read) else None
        self._last_read = pos

        if pos is not None and counts_delta(pos, self._target) <= self.config.tolerance_counts:
            target, box = self._target, self._box
            self._target = None
            self.arrived += 1
            logger.info("转盘到位：货格 %s 目标 %d 读回 %d（差 %d counts ≤ %d）",
                        box, target, pos, counts_delta(pos, target),
                        self.config.tolerance_counts)
            return None

        if now >= self._deadline:
            reason = (
                "转盘到位超时：货格 %s 目标 %s，读回 %s，容差 ±%d counts，"
                "限时 %.1fs（起转后 %.2fs）"
                % (
                    self._box, self._target,
                    "读不到" if pos is None else pos,
                    self.config.tolerance_counts, self.config.timeout_s,
                    now - self._issued_at,
                )
            )
            self._failed = reason
            self._target = None
            self.turntable.lock(reason)
            logger.error("%s —— 锁转盘、停链（fail-closed）", reason)
            return reason
        return None

    def note_motion_done(self) -> None:
        """收到 MOTION_DONE 时调用：转盘此刻必须已确认到位，否则本件可能在转动中落料。"""
        if self._target is None:
            return
        waited = self._clock() - self._issued_at
        self.unverified_at_motion_done += 1
        reason = (
            "🔴 MOTION_DONE 到达时转盘仍未确认到位（货格 %s 目标 %s，读回 %s，"
            "起转后 %.2fs，限时 %.1fs）—— 本件可能在转盘中落料。停链排查。"
            % (self._box, self._target,
               "读不到" if self._last_read is None else self._last_read,
               waited, self.config.timeout_s)
        )
        self._failed = reason
        self._target = None
        self.turntable.lock(reason)
        logger.error("%s", reason)

    @property
    def failed(self) -> str | None:
        return self._failed

    def close(self) -> None:  # 后端由 Turntable 持有，这里不闭
        return


__all__ = [
    "ArrivalConfig",
    "COUNTS_PER_TURN",
    "PositionTurnGuard",
    "counts_delta",
]
