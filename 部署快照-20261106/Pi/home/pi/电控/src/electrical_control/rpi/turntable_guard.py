"""转盘「该翻不翻 / 翻没翻到位」的运行时守卫（方案C 专用）。

边界声明（先写清权力，再写实现）
--------------------------------
本模块**只管时序与校验**，不管：

* 落料点坐标 —— 在 `drop_strategy`（[DropPoints]，6 行，4/5/6 = 1/2/3）；
* 脉宽换算与越界拦截 —— 在 `turntable.TurntableConfig`；
* 写 `pw.txt` / 释放 / 锁定 —— 在 `turntable.Turntable`。

**本模块不直接写文件、不直接碰 GPIO18**；唯一的 GPIO 动作是**只读 GPIO17**（索引开关）。

它只做三件事：

1. **派发前**（`before_dispatch`）：算"这件要不要翻"。要翻 ⇒ 立刻 `command_box()`
   下发脉宽（O(1)、**不等整定**）⇒ 舵机转动与滑台十几秒的运动**并行**，不占 15s 失活窗
   （2026-09-21 用户裁决：转盘动作计入窗口，串行会白吃 1~2s 余量）。
2. **到点后**（`poll`）：`settle_s` 到期读一次 GPIO17 索引，与期望侧比对。
3. **失败即锁死**：索引不符 / 读不到 / 到位晚于 `MOTION_DONE` ⇒ 记 ERROR、锁转盘，
   并让调用方**停链**（fail-closed）。

为什么"转到位"不能只靠 sleep
----------------------------
* `pi_pw.py` 对 500–2500 之外的脉宽是 try/except **吞掉**的 ⇒ 写了个非法值**不报错、
  舵机也不动**。"下发了" ≠ "转过去了"。⇒ 唯一能证明转盘真的动了的是**索引开关**。
* 位置舵机的绝对零点会漂（断电时输出轴可被拧动）⇒ 索引同时是零点安全网。
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from electrical_control.rpi.drop_strategy import SIDE_A, SIDE_B
from electrical_control.rpi.turntable import (
    FakeBackend,
    PwFileBackend,
    Turntable,
    TurntableError,
    TurntableUncalibrated,
    make_backend,
)

logger = logging.getLogger(__name__)

DEFAULT_INDEX_PIN = 17


# ---------------------------------------------------------------------------
# 索引开关（只读）
# ---------------------------------------------------------------------------

class IndexReader(Protocol):
    """索引开关只读接口。返回 True = 引脚读高。"""

    def level(self) -> bool: ...
    def close(self) -> None: ...


class PigpioIndexReader:
    """GPIO17（内部上拉、无外部电阻）只读实现。

    ⚠️ 只做 `set_mode(INPUT)` + `set_pull_up_down(PUD_UP)` + `read()`：
    **不碰 GPIO18**，因此不会与常驻 `pi_pw.py` 对舵机引脚的占用冲突
    （pigpio 的舵机脉冲随**它自己的**客户端断连而撤销，与本连接无关）。
    `close()` 只关本连接。
    """

    def __init__(self, pin: int = DEFAULT_INDEX_PIN) -> None:
        import pigpio  # 延迟导入：主机上没装也能 import 本模块做离线测试

        self.pin = pin
        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise TurntableError("pigpiod 未运行（systemctl start pigpiod）—— 索引开关读不到")
        self._pi.set_mode(pin, pigpio.INPUT)
        self._pi.set_pull_up_down(pin, pigpio.PUD_UP)

    def level(self) -> bool:
        value = self._pi.read(self.pin)
        if value < 0:
            raise TurntableError(f"GPIO{self.pin} 读失败（pigpio 返回 {value}）")
        return bool(value)

    def close(self) -> None:
        self._pi.stop()


class FakeIndexReader:
    """离线假件：`level_fn()` 每次读都重新求值 ⇒ 假索引"跟着指令走"。"""

    def __init__(self, level_fn: Callable[[], bool]) -> None:
        self._level_fn = level_fn
        self.reads = 0

    def level(self) -> bool:
        self.reads += 1
        return bool(self._level_fn())

    def close(self) -> None:
        return


# ---------------------------------------------------------------------------
# 守卫
# ---------------------------------------------------------------------------

class TurntableGuard:
    """一件一转的时序记账。**单线程使用**（主循环里同步调用）。"""

    def __init__(
        self,
        *,
        turntable: Turntable,
        side_of_box: dict[int, str],
        index_reader: IndexReader | None = None,
        index_side: str | None = None,
        index_timeout_s: float = 0.5,
    ) -> None:
        self.turntable = turntable
        self._side_of_box = dict(side_of_box)
        self._index = index_reader
        self._index_side = index_side
        self._index_timeout_s = index_timeout_s

        self._side: str | None = None      # 记账：转盘现在在哪一侧（None = 未知）
        self._expect: str | None = None    # 本件要校验的侧（None = 本件不用翻）
        self._due_at = 0.0                 # 起转时刻 + settle_s
        self._give_up_at = 0.0             # + index_timeout_s（仅作重读窗口）
        self._issued_at = 0.0
        self._failed: str | None = None

        # 诊断计数（只读，给日志/复盘用）
        self.turns = 0
        self.unverified_at_motion_done = 0

        if self._index_side is None:
            logger.warning(
                "转盘索引开关未启用（index_side=none）：到位只按 settle_s=%.1fs 计时判定，"
                "**没有硬件确认**。位置舵机零点会漂（断电时可被拧动），本模式仅在没有可用"
                "索引、或索引挡片与 180° 对称结构冲突时使用。",
                turntable.config.settle_s,
            )

    # ---- 开工前 ----

    def preflight(self) -> None:
        """开工前把转盘**阻塞**摆到 A 侧并校验一次；失败即 raise（调用方拒绝开轮）。

        它会**真的让舵机转** —— 这是有意的：宁可开工前发现零点漂了，
        也不要第一件就投错格。
        """
        box = min((b for b, s in self._side_of_box.items() if s == SIDE_A), default=None)
        if box is None:
            raise TurntableUncalibrated("方案C：A 侧一个货格都没有，无法预置")
        self.turntable.goto_box(box)       # 阻塞 settle_s
        self.turns += 1
        self._side = SIDE_A
        self._verify(SIDE_A)               # 索引不符即 raise
        logger.warning(
            "转盘开工自检通过：已摆到 A 侧（货格 %d）。⚠️ 现场纪律："
            "现在指针应停在盘面「线 0」（1500µs）。不在 ⇒ 立刻停，重标定，不要开轮。",
            box,
        )

    # ---- 每件 ----

    def before_dispatch(self, box_id: int) -> str | None:
        """**发 ITEM_TASK 之前**调用。返回 None = 可以派件；否则 = 拒做原因（要停链）。"""
        if self._failed is not None:
            return self._failed
        side = self._side_of_box.get(box_id)
        if side is None:
            return f"货格 {box_id} 没有配转盘侧（[TurntableSides] 应为 6 行、每行 a|b）"
        if side == self._side:
            self._expect = None            # 同侧：不翻、不需要到位校验
            return None
        pulse = self.turntable.command_box(box_id)   # 越界/锁定 ⇒ 抛（调用方 fail-closed）
        now = time.monotonic()
        self._side = side
        self._expect = side
        self._issued_at = now
        self._due_at = now + self.turntable.config.settle_s
        self._give_up_at = self._due_at + self._index_timeout_s
        self.turns += 1
        logger.info("转盘翻转 → %s 侧（%dµs）。**不等整定**，与滑台运动并行。", side, pulse)
        return None

    def poll(self) -> str | None:
        """主循环每轮调用（很便宜：不到点直接 return）。返回非 None 时链路必须停。"""
        if self._failed is not None:
            return self._failed
        if self._expect is None:
            return None
        if self._index_side is None:
            # 无索引：到 settle_s 即认为到位（构造时已打过 WARNING）
            if time.monotonic() >= self._due_at:
                self._expect = None
            return None
        now = time.monotonic()
        if now < self._due_at:
            return None
        try:
            self._verify(self._expect)
        except TurntableError as exc:
            if now < self._give_up_at:
                return None                # 挡片可能还在跳变：下一轮再读一次
            self._failed = f"转盘到位校验失败（期望 {self._expect} 侧）：{exc}"
            self.turntable.lock(self._failed)
            return self._failed
        self._expect = None
        return None

    def note_motion_done(self) -> None:
        """收到 MOTION_DONE 时调用：核对"本件落料时转盘是否已确认到位"。

        转盘在 `before_dispatch` 就起转、滑台要走十余秒，正常情况下 `_expect`
        早已清空。若此刻**仍在等校验**，说明本件的落料发生在"转盘位置未被确认"
        的窗口里 —— 记 ERROR 并锁死，绝不把同一个错误重复到下一件。
        """
        if self._expect is None:
            return
        waited = time.monotonic() - self._issued_at
        self.unverified_at_motion_done += 1
        self._failed = (
            f"🔴 MOTION_DONE 到达时转盘仍未确认到位（期望 {self._expect} 侧，"
            f"起转后已 {waited:.2f}s，settle_s={self.turntable.config.settle_s:.2f}s）"
            "—— 本件可能在转盘中落料。停链排查 settle_s / 索引 / 舵机供电。"
        )
        self.turntable.lock(self._failed)

    @property
    def failed(self) -> str | None:
        return self._failed

    # ---- 内部 ----

    def _verify(self, side: str) -> None:
        if self._index_side is None:
            return
        assert self._index is not None, "index_side 已配置却没有任何索引读值器"
        want = (side == self._index_side)
        got = self._index.level()
        if got != want:
            raise TurntableError(
                f"索引 GPIO{getattr(self._index, 'pin', '?')} 读 {int(got)}，"
                f"期望 {int(want)}（{side} 侧）"
            )

    def close(self) -> None:
        if self._index is not None:
            self._index.close()


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------

def build_turn_guard(strategy, *, demo: bool = False) -> TurntableGuard | None:
    """方案C 才构造；方案A/B 返回 None。

    返回 None ⇒ `run_chain` 主循环里所有转盘代码整体不执行（零文件写、零 GPIO 动作）。
    """
    if not (strategy.requires_turntable_control() and strategy.uses_drop_points()):
        return None

    config = strategy.turntable_config
    index_side = strategy.index_side
    if demo:
        turntable = Turntable(config, FakeBackend())

        # 假索引：模拟"**挡片物理上固定在 A 侧被挡住**"这一实物事实，
        # **不由 index_side 反推** —— 否则假索引永远自洽，
        # "index_side 配反"这类错误就永远测不出来（同义反复的测试）。
        def _level() -> bool:
            current = turntable.current_box
            if current is None:
                return False
            return strategy.side_for_box(current) == SIDE_A

        index_reader: IndexReader | None = FakeIndexReader(_level)
    else:
        # 2026-10-17：转盘改为 ST-3215 总线舵机（走 UART2 /dev/ttyAMA1）。
        # make_backend() 默认返回 SerialServoBackend；旧的 PWM 方案仍可用
        # 环境变量 TURNTABLE_BACKEND=pw 临时回退。
        turntable = Turntable(config, make_backend())
        index_reader = PigpioIndexReader(strategy.index_pin) if index_side else None

    return TurntableGuard(
        turntable=turntable,
        side_of_box=strategy.side_of_box(),
        index_reader=index_reader,
        index_side=index_side,
    )


# ---------------------------------------------------------------------------
# 离线自检（不连硬件、不写 pw.txt、不碰 GPIO）
# ---------------------------------------------------------------------------

def _self_check() -> int:
    import configparser

    from electrical_control.rpi.drop_strategy import load_strategy_from_cfg

    INI = """[DropPoints]
1 = -25.0, 87.5
2 = -95.0, 47.5
3 = 45.0, 47.5
4 = -25.0, 87.5
5 = -95.0, 47.5
6 = 45.0, 47.5

[TurntablePositions]
center_us = 1500
us_per_90deg = 655
angle_a = 90
angle_b = -90
settle_s = 0.05
index_side = {idx}
index_pin = 17

[TurntableSides]
1 = a
2 = a
3 = a
4 = b
5 = b
6 = b
"""

    def _mk(index_side: str):
        # ⚠️ 内存解析，**不碰文件系统**：不需要临时目录，也不往 CWD 落文件。
        cfg = configparser.ConfigParser()
        cfg.read_string(INI.format(idx=index_side))
        return load_strategy_from_cfg(cfg, "<selftest>")

    fails = 0

    def check(cond: bool, tag: str) -> None:
        nonlocal fails
        if cond:
            print("  ✓ " + tag)
        else:
            fails += 1
            print("  ✗ " + tag)

    print("=== turntable_guard 自检（离线）===")

    # ---------------------------------------------------------------- 1/2
    strat = _mk("none")
    g = build_turn_guard(strat, demo=True)
    assert g is not None
    check(g is not None, "[1] 方案C ⇒ 构造出守卫")
    check(build_turn_guard(_mk("none")) is not None, "[2] 非 demo 也构造（但会写 pw.txt，这里不调用动作）")

    be = g.turntable.backend
    check(hasattr(be, "pulses"), "    （假后端记录脉宽）")

    # ---------------------------------------------------------------- 3 预置
    g.preflight()
    check(be.pulses == [845], "[3] preflight 阻塞摆到 A 侧、只发一次 845µs")
    check(g.turntable.current_box == 1, "    current_box=1")

    # ---------------------------------------------------------------- 4 同侧不翻
    n_before = len(be.pulses)
    r = g.before_dispatch(2)          # 2 也在 A 侧
    check(r is None and len(be.pulses) == n_before, "[4] 同侧不翻 ⇒ 一个字节都不写")

    # ---------------------------------------------------------------- 5 交替翻
    check(g.before_dispatch(4) is None, "[5a] 4 在 B 侧 ⇒ 下发")
    check(be.pulses[-1] == 2155, "     [5b] B 侧脉宽 = 2155µs")
    check(g.before_dispatch(1) is None, "[5c] 回 A 侧")
    check(be.pulses[-1] == 845, "     [5d] A 侧脉宽 = 845µs")
    check(be.pulses == [845, 2155, 845], "     [5e] 脉宽序列 = [845, 2155, 845]")

    # ---------------------------------------------------------------- 6/7 索引校验
    g2 = build_turn_guard(_mk("a"), demo=True)
    assert g2 is not None
    g2.preflight()                    # A 侧 ⇒ 期望读高
    check(g2._index.reads == 1, "[6] preflight 读一次索引")
    check(g2.before_dispatch(4) is None, "[7a] 翻到 B 侧（不阻塞）")
    check(g2._index.reads == 1, "     [7b] settle_s 未到 ⇒ 不读索引")
    for _ in range(80):
        if g2.poll() is not None:
            break
        time.sleep(0.02)
    check(g2.failed is None, "     [7c] 到点后校验通过（假索引跟着指令走）")

    # ---------------------------------------------------------------- 8 索引配反
    g3 = build_turn_guard(_mk("b"), demo=True)
    assert g3 is not None
    try:
        g3.preflight()
        check(False, "[8] index_side 配反 ⇒ 开工自检应当 raise")
    except TurntableError:
        check(True, "[8] index_side 配反 ⇒ 开工自检当场拦住")

    # ---------------------------------------------------------------- 9 运行中掉索引 ⇒ 锁死
    g4 = build_turn_guard(_mk("a"), demo=True)
    assert g4 is not None
    g4.preflight()
    g4.before_dispatch(4)
    g4._index = FakeIndexReader(lambda: True)   # 挡片掉了：B 侧却读高
    for _ in range(120):
        if g4.poll() is not None:
            break
        time.sleep(0.02)
    check(g4.failed is not None and "到位校验失败" in (g4.failed or ""),
          "[9a] 运行中索引不符 ⇒ 锁死")
    check(g4.before_dispatch(1) == g4.failed, "[9b] 锁死是持久的（不再派件）")

    # ---------------------------------------------------------------- 10 无索引
    g5 = build_turn_guard(_mk("none"), demo=True)
    assert g5 is not None
    g5.preflight()
    g5.before_dispatch(4)
    check(g5._index.reads == 0 if hasattr(g5._index, "reads") else True,
          "[10] index_side=none ⇒ 到位只按时间判（构造时已 WARNING）")
    for _ in range(120):
        if g5.poll() is not None:
            break
        time.sleep(0.02)
    check(g5.failed is None, "     到点即认为到位")

    # ---------------------------------------------------------------- 11 落料窗口未确认
    g6 = build_turn_guard(_mk("a"), demo=True)
    assert g6 is not None
    g6.preflight()
    g6.before_dispatch(4)
    g6.note_motion_done()                    # settle 未到就收到 MOTION_DONE
    check(g6.failed is not None and "MOTION_DONE" in (g6.failed or ""),
          "[11a] 落料时转盘未确认到位 ⇒ 记 ERROR + 锁死")
    check(g6.unverified_at_motion_done == 1, "[11b] 计数 +1")

    # ---------------------------------------------------------------- 12 缺侧
    g7 = build_turn_guard(_mk("none"), demo=True)
    assert g7 is not None
    check(g7.before_dispatch(99) is not None, "[12] 未配侧的货格 ⇒ 返回拒做原因")

    print()
    if fails:
        print(f"❌ {fails} 项未通过")
        return 1
    print("🎉 turntable_guard 自检全部通过")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_self_check())
