"""转盘驱动（树莓派侧）—— 角度 → 舵机脉宽 → 输出。

边界声明（先写清楚，避免隐式越权）
----------------------------------
本模块**只做一件事**：把一个「货格角度」换算成一个舵机脉宽，并把它交给一个
**后端**去输出。它：

* **不**修改 `ITEM_TASK`、**不**碰串口协议、**不**改固件 —— 因此**不触发 L4**。
* **不**自己决定"现在该转哪一格" —— 那是调用方（`drop_strategy.TurntableStrategy.get_angle`
  或 `run_chain` 的接入点）的事。
* **不**连线、不上电、不做任何实机动作，除非调用方显式调用 `goto_box()`。
* **不**假设任何未实测的标定值：所有物理量都必须由配置显式给出，缺一个就 fail-closed。

已实测的标定事实（2026-09-21，见 `当前进度与交接.md` §14.9 / §14.12）
------------------------------------------------------------------
* 舵机是**位置舵机**，不是连续旋转型：发同一个脉宽 N 次，轴 N 次都在同一个位置（不累加）。
* 盘面「线 0」= **1500 µs**；「线 1」= **845 µs**（用户目视确认）⇒ **90° ≈ 655 µs**。
* **脉宽减小 = 顺时针**（以本次装夹方向为准）。
* 行程两端 ≈ **500 µs / 2500 µs**（同时是 pigpio 的硬限，传越界值会抛
  `pigpio.error: 'pulsewidth not 0 or 500-2500'`）。
* ⇒ **总行程约 270°**，1500 µs 是正中间。**360° 分度做不到**，6 格必须排在 270° 弧内
  （每格 45°、围绕中点对称布置时脉宽范围约 681~2319 µs，落在可用区间内）。

🔴 未验证 / 待现场确认
--------------------
* 「线 0 = 1500 µs」是**本次装夹**下的结果；若转盘重新装夹，零点会变，必须重标。
* 「断电时输出轴可被手动无限转动」与「位置舵机」互相矛盾，**至今未解释**。
  ⚠️ 因此：**断电时禁止用手拧舵机输出轴**；每次开工前做一次零点自检
  （发 `zero_pulse_us`，目视指针是否仍在线 0）。
* 6 格 45° 间距**尚未由机械组确认**（判据：转盘半径 ≥ 70mm 时扇区弧长约 55mm，
  要装得下 40mm 的件）。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# pigpio 硬限（越界会抛异常，不是我们设的）
PULSE_MIN_US = 500
PULSE_MAX_US = 2500
# 0 = 释放（无脉冲，舵机失力）。除调试外不要用。
PULSE_RELEASE_US = 0

# ST-3215 总线舵机的位置域（0~4095 覆盖 360°）。2026-11-07 新增位置域 API：
# 360° 分度下角度可到 ±180°，脉宽域 [500,2500]µs 只有 ±137° ⇒ 再走脉宽域会被拦死。
POS_MIN = 0
POS_MAX = 4095

DEFAULT_PW_FILE = "/home/pi/pw.txt"


class TurntableError(RuntimeError):
    """转盘模块异常基类。"""


class TurntableUncalibrated(TurntableError):
    """标定缺失或非法 —— fail-closed，绝不猜。"""


class TurntableLocked(TurntableError):
    """已锁定（标定被判定失效 / 硬件故障），拒绝动作。"""


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TurntableConfig:
    """转盘标定配置。

    所有物理量都必须**由调用方显式给出**，本类不给任何"看起来合理"的默认值 ——
    默认值就是猜，猜错的后果是撞机构或放错格。

    Args:
        zero_pulse_us: 角度 0 对应的脉宽（µs）。本次装夹 = 1500。
        us_per_degree: 每度对应多少 µs。本次实测 = 655/90 ≈ 7.2778。
        angle_sign: +1 表示「角度增大 → 脉宽增大」，-1 表示相反。
                    本次装夹实测：脉宽减小 = 顺时针 ⇒ 顺时针为正角度时取 -1。
        angle_table: {box_id: 角度(度)}。角度基准由 zero_pulse_us 定义。
        settle_s: 转到位后等待整定的时间（秒）。
        name: 便于日志识别。
    """

    zero_pulse_us: int
    us_per_degree: float
    angle_sign: int
    angle_table: dict[int, float] = field(default_factory=dict)
    settle_s: float = 0.6
    name: str = "turntable"
    # 🔴 2026-11-07：位置域直通参数（ST-3215）。360° 分度必须走位置域，
    #    因为脉宽域 [500,2500]µs 只能覆盖 ±137°，±180° 会被 fail-closed 拦死。
    #    与 SerialServoBackend 的同名默认值保持一致（2026-10-17 实测）。
    center_pos: int = 2048
    counts_per_90: int = 1024

    def __post_init__(self) -> None:
        if not (PULSE_MIN_US <= self.zero_pulse_us <= PULSE_MAX_US):
            raise TurntableUncalibrated(
                f"zero_pulse_us={self.zero_pulse_us} 不在 [{PULSE_MIN_US},{PULSE_MAX_US}]"
            )
        if self.us_per_degree <= 0:
            raise TurntableUncalibrated(f"us_per_degree={self.us_per_degree} 必须 > 0")
        if self.angle_sign not in (-1, 1):
            raise TurntableUncalibrated(f"angle_sign={self.angle_sign} 只能是 +1/-1")
        if self.settle_s < 0:
            raise TurntableUncalibrated(f"settle_s={self.settle_s} 不能为负")
        if not (POS_MIN <= self.center_pos <= POS_MAX):
            raise TurntableUncalibrated(
                f"center_pos={self.center_pos} 不在 [{POS_MIN},{POS_MAX}]"
            )
        if self.counts_per_90 <= 0:
            raise TurntableUncalibrated(
                f"counts_per_90={self.counts_per_90} 必须 > 0"
            )

    # ---- 换算（脉宽域，旧）----

    def pulse_for_angle(self, angle_deg: float) -> int:
        """角度 → 脉宽（四舍五入到 µs）。**越界即 raise，不做 clamp 静默截断。**"""
        raw = self.zero_pulse_us + self.angle_sign * angle_deg * self.us_per_degree
        pulse = int(round(raw))
        if not (PULSE_MIN_US <= pulse <= PULSE_MAX_US):
            raise TurntableUncalibrated(
                f"角度 {angle_deg:.1f}° → 脉宽 {pulse}µs 超出 [{PULSE_MIN_US},{PULSE_MAX_US}]"
                f"（零位 {self.zero_pulse_us}µs、{self.us_per_degree:.4f}µs/度）。"
                f"若这是第 6 格，说明 6 格没排进行程 —— 见模块头注释。"
            )
        return pulse

    # ---- 换算（位置域，2026-11-07 新增）----

    @property
    def us_per_90(self) -> float:
        return self.us_per_degree * 90.0

    def pos_for_angle(self, angle_deg: float) -> int:
        """角度 → 位置值（0~4095）。**越界即 raise**，与脉宽域同一 fail-closed 口径。

        与 `pulse_for_angle` 同一条直线：把「角度→脉宽」的位移按
        `counts_per_90 / us_per_90` 换成位置位移，基准是 `center_pos`。
        """
        delta_us = self.angle_sign * float(angle_deg) * self.us_per_degree
        raw = self.center_pos + delta_us * self.counts_per_90 / self.us_per_90
        pos = int(round(raw))
        if not (POS_MIN <= pos <= POS_MAX):
            raise TurntableUncalibrated(
                f"角度 {angle_deg:.1f}° → 位置 {pos} 超出 [{POS_MIN},{POS_MAX}]"
                f"（中位 {self.center_pos}、{self.counts_per_90}counts/90°、sign={self.angle_sign:+d}）"
            )
        return pos

    def pulse_for_position(self, pos: int) -> int:
        """位置值 → 脉宽（仅 ±137° 内可用）。给只有脉宽后端（pw/pigpio）的兼容路径用。"""
        delta_pos = int(pos) - self.center_pos
        pulse = int(round(self.zero_pulse_us + delta_pos * self.us_per_90 / self.counts_per_90))
        if not (PULSE_MIN_US <= pulse <= PULSE_MAX_US):
            raise TurntableUncalibrated(
                f"位置 {pos} → 脉宽 {pulse}µs 超出 [{PULSE_MIN_US},{PULSE_MAX_US}]："
                f"该后端只支持 ±137°，360° 请用 SerialServoBackend（位置域）"
            )
        return pulse

    def angle_for_box(self, box_id: int) -> float:
        """货格号 → 角度。表里没有就 fail-closed，**不猜**。"""
        if box_id not in self.angle_table:
            raise TurntableUncalibrated(
                f"货格 {box_id} 不在角度表里（表内只有 {sorted(self.angle_table)}）"
            )
        return self.angle_table[box_id]

    def pulse_for_box(self, box_id: int) -> int:
        return self.pulse_for_angle(self.angle_for_box(box_id))

    def pos_for_box(self, box_id: int) -> int:
        """货格号 → 位置值（0~4095）。360° 分度的生产路径。"""
        return self.pos_for_angle(self.angle_for_box(box_id))

    def coverage(self) -> tuple[int, int]:
        """角度表里最小/最大脉宽 —— 上机前用它自查有没有越界。"""
        pulses = [self.pulse_for_angle(a) for a in self.angle_table.values()]
        return (min(pulses), max(pulses)) if pulses else (0, 0)

    def position_coverage(self) -> tuple[int, int]:
        """角度表里最小/最大位置值 —— 360° 上机前自查用。"""
        positions = [self.pos_for_angle(a) for a in self.angle_table.values()]
        return (min(positions), max(positions)) if positions else (0, 0)


# ---------------------------------------------------------------------------
# 后端（输出通道）
# ---------------------------------------------------------------------------

class PulseBackend(Protocol):
    """脉宽输出后端。两条实现都在本文件内，便于离线测试注入假件。"""

    def set_pulse_us(self, pulse_us: int) -> None: ...
    def close(self) -> None: ...


class PwFileBackend:
    """写 `/home/pi/pw.txt`，由常驻进程 `pi_pw.py` 持续输出。

    **选它的理由**：pigpio 在客户端断开连接时会撤销舵机脉冲；`pi_pw.py` 是一条
    **常驻**连接，所以脉宽能一直保持（2026-09-21 实测确认：这是"发了脉宽舵机却
    不动/回弹"的真因）。本后端只是往文件里写一个数，不自己开串口、不自己发光。

    ⚠️ 前提：`pi-pwm.service` 在跑（`systemctl is-active pi-pwm`）。
    """

    def __init__(self, path: str | Path = DEFAULT_PW_FILE) -> None:
        self.path = Path(path)

    def set_pulse_us(self, pulse_us: int) -> None:
        if pulse_us != PULSE_RELEASE_US and not (PULSE_MIN_US <= pulse_us <= PULSE_MAX_US):
            raise TurntableError(f"拒绝下发 {pulse_us}µs：超出 [{PULSE_MIN_US},{PULSE_MAX_US}]")
        # 先写临时文件再原子替换，避免常驻进程读到半截数字
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(f"{pulse_us}\n", encoding="ascii")
        os.replace(tmp, self.path)

    def close(self) -> None:  # 无资源可释放，保持接口一致
        return


class PigpioBackend:
    """直接连 pigpiod 输出。**仅在调用方自己负责保持连接时使用**。

    注意：进程退出 ⇒ 连接断开 ⇒ pigpio 撤销脉冲 ⇒ 舵机失力。日常部署请用
    `PwFileBackend`。
    """

    def __init__(self, pin: int = 18) -> None:
        import pigpio  # 延迟导入：主机上没有这个库也能 import 本模块做离线测试

        self.pin = pin
        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise TurntableError("pigpiod 未运行（systemctl start pigpiod）")

    def set_pulse_us(self, pulse_us: int) -> None:
        if pulse_us != PULSE_RELEASE_US and not (PULSE_MIN_US <= pulse_us <= PULSE_MAX_US):
            raise TurntableError(f"拒绝下发 {pulse_us}µs：超出 [{PULSE_MIN_US},{PULSE_MAX_US}]")
        self._pi.set_servo_pulsewidth(self.pin, pulse_us)

    def close(self) -> None:
        try:
            self._pi.set_servo_pulsewidth(self.pin, PULSE_RELEASE_US)
        finally:
            self._pi.stop()


class SerialServoBackend:
    """通过 UART2 驱动 ST-3215 总线舵机（微雪 Bus Servo Adapter A）。

    2026-10-17 实测打通。本后端把上层给的**脉宽**换算成舵机**位置值**再发串行
    指令，因此 `TurntableConfig` / `Turntable` / `run_chain.py` **全部无需改动**，
    配置文件里的 `center_us` / `us_per_90deg` 也继续有效。

    标定换算（实测）::

        position = center_pos + (pulse_us - center_us) * counts_per_90 / us_per_90deg

        默认 center_us=1500, us_per_90deg=655, center_pos=2048, counts_per_90=1024
        ⇒ pulse  845 → 1024 (= A 侧)
          pulse 1500 → 2048 (= 中位)
          pulse 2155 → 3072 (= B 侧)

    硬件与协议要点（踩过的坑，改之前务必看）
    ----------------------------------------
    * 转换板 UART 口是 **同名直连**：Pi TX→板 TX、Pi RX→板 RX（**不是交叉**！
      交叉接会完全无响应，0 字节）。
    * `/boot/config.txt` 需要 `dtoverlay=uart2` 才有 `/dev/ttyAMA1`（GPIO0/1）。
    * 舵机 ID=1，波特率 **1,000,000**（1 Mbps）。
    * 帧：``FF FF ID LEN INST PARAM... CS``；``LEN = 参数数 + 2``；
      ``CS = ~(ID+LEN+INST+PARAM...) & 0xFF``。
    * 寄存器：目标位置 0x2A、目标时间 0x2C、当前位置 0x38（均 2 字节小端）。

    环境变量：``TURNTABLE_SERIAL_PORT``（默认 /dev/ttyAMA1）
              ``TURNTABLE_SERIAL_BAUD``（默认 1000000）
              ``TURNTABLE_SERVO_ID``（默认 1）
              ``TURNTABLE_MOVE_MS``（默认 1500，移动耗时=限速）
    """

    ADDR_GOAL_POS = 0x2A
    ADDR_GOAL_TIME = 0x2C
    ADDR_PRESENT_POS = 0x38

    INST_PING = 0x01
    INST_READ = 0x02
    INST_WRITE = 0x03

    def __init__(
        self,
        port: str | None = None,
        baud: int | None = None,
        servo_id: int | None = None,
        *,
        center_us: int = 1500,
        us_per_90: int = 655,
        center_pos: int = 2048,
        counts_per_90: int = 1024,
        move_ms: int | None = None,
    ) -> None:
        import serial  # 延迟导入：主机上没有 pyserial 也能 import 本模块做离线测试

        self.port = port or os.environ.get("TURNTABLE_SERIAL_PORT", "/dev/ttyAMA1")
        self.baud = int(baud or os.environ.get("TURNTABLE_SERIAL_BAUD", "1000000"))
        self.sid = int(servo_id or os.environ.get("TURNTABLE_SERVO_ID", "1"))
        self.center_us = int(center_us)
        self.us_per_90 = int(us_per_90)
        self.center_pos = int(center_pos)
        self.counts_per_90 = int(counts_per_90)
        self.move_ms = int(move_ms or os.environ.get("TURNTABLE_MOVE_MS", "1500"))
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.12)
        except Exception as exc:  # noqa: BLE001
            raise TurntableError(
                "转盘串口打不开 %s@%d：%s" % (self.port, self.baud, exc)
            ) from exc
        # 实测：开串口后约需 0.2s 总线才稳定，否则紧接着的前几次 PING 会失败
        time.sleep(0.2)
        try:
            self._ser.reset_input_buffer()
        except Exception:  # noqa: BLE001
            pass

    # -- 协议 ------------------------------------------------------------
    @staticmethod
    def _checksum(body):
        return (~sum(body)) & 0xFF

    def _frame(self, body):
        return bytes([0xFF, 0xFF] + list(body) + [self._checksum(body)])

    def _read_packet(self):
        buf = self._ser.read(32)
        i = buf.find(b"\xff\xff")
        if i < 0 or len(buf) < i + 4:
            return None
        ln = buf[i + 3]
        need = i + 4 + ln
        if len(buf) < need:
            buf += self._ser.read(need - len(buf))
        if len(buf) < need:
            return None
        return {"err": buf[i + 4], "data": buf[i + 5:i + 4 + ln - 1]}

    def _txn(self, body, wait: float = 0.06):
        self._ser.reset_input_buffer()
        self._ser.write(self._frame(body))
        self._ser.flush()
        time.sleep(wait)
        return self._read_packet()

    def _write16(self, addr: int, value: int) -> bool:
        v = int(value) & 0xFFFF
        r = self._txn([self.sid, 5, self.INST_WRITE, addr, v & 0xFF, v >> 8])
        return r is not None and r["err"] == 0

    # -- 对外 ------------------------------------------------------------
    def ping(self) -> bool:
        r = self._txn([self.sid, 2, self.INST_PING])
        return r is not None and r["err"] == 0

    def read_pos(self) -> int | None:
        r = self._txn([self.sid, 4, self.INST_READ, self.ADDR_PRESENT_POS, 2])
        if r is None or len(r["data"]) < 2:
            return None
        return r["data"][0] | (r["data"][1] << 8)

    def pos_for_pulse(self, pulse_us: int) -> int:
        """脉宽（µs）→ 舵机位置值（0~4095）。"""
        raw = self.center_pos + (
            (int(pulse_us) - self.center_us)
            * self.counts_per_90
            / float(self.us_per_90)
        )
        return int(round(max(0.0, min(4095.0, raw))))

    def set_pulse_us(self, pulse_us: int) -> None:
        pulse_us = int(pulse_us)
        if pulse_us == PULSE_RELEASE_US:
            # 总线舵机会保持最后位置；不做「失力」，避免转盘被外力自由转动
            logger.debug("SerialServoBackend：忽略释放指令，保持当前位置")
            return
        if not (PULSE_MIN_US <= pulse_us <= PULSE_MAX_US):
            raise TurntableError(
                "拒绝下发 %dµs：超出 [%d,%d]"
                % (pulse_us, PULSE_MIN_US, PULSE_MAX_US)
            )
        pos = self.pos_for_pulse(pulse_us)
        if not self._write16(self.ADDR_GOAL_TIME, self.move_ms):
            raise TurntableError("转盘舵机无响应（写目标时间失败，%s）" % self.port)
        if not self._write16(self.ADDR_GOAL_POS, pos):
            raise TurntableError("转盘舵机无响应（写目标位置失败，%s）" % self.port)
        logger.debug("转盘 %dµs → 位置 %d", pulse_us, pos)

    def set_position(self, pos: int) -> None:
        """🔴 2026-11-07：位置域直发（0~4095，覆盖 360°）。**不经过脉宽换算**。

        360° 分度必须走这条路：脉宽域 [500,2500]µs 只有 ±137°，±180° 会被拦住。
        """
        pos = int(pos)
        if not (POS_MIN <= pos <= POS_MAX):
            raise TurntableError(
                "拒绝下发位置 %d：超出 [%d,%d]" % (pos, POS_MIN, POS_MAX)
            )
        if not self._write16(self.ADDR_GOAL_TIME, self.move_ms):
            raise TurntableError("转盘舵机无响应（写目标时间失败，%s）" % self.port)
        if not self._write16(self.ADDR_GOAL_POS, pos):
            raise TurntableError("转盘舵机无响应（写目标位置失败，%s）" % self.port)
        logger.debug("转盘 位置 %d", pos)

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass


def make_backend(kind: str | None = None) -> PulseBackend:
    """按环境变量 ``TURNTABLE_BACKEND`` 选择后端。

    ``serial``（默认）→ `SerialServoBackend`（ST-3215 总线舵机，2026-10-17 起）
    ``pw``            → `PwFileBackend`（旧 PWM 方案，已作废，仅作兼容）
    ``pigpio``        → `PigpioBackend`（直连 pigpiod）
    """
    kind = (kind or os.environ.get("TURNTABLE_BACKEND", "serial")).strip().lower()
    if kind in ("pw", "pwfile"):
        logger.warning(
            "TURNTABLE_BACKEND=pw：使用**已作废**的 PWM 方案，ST-3215 不会转动"
        )
        return PwFileBackend()
    if kind == "pigpio":
        return PigpioBackend()
    return SerialServoBackend()


# ---------------------------------------------------------------------------
# 驱动
# ---------------------------------------------------------------------------

class Turntable:
    """转盘：转到某个货格 / 回到零位 / 停止。

    用法（离线装配，不发光）::

        cfg = TurntableConfig(zero_pulse_us=1500, us_per_degree=655/90,
                              angle_sign=-1,
                              angle_table={1: -112.5, 2: -67.5, 3: -22.5,
                                           4: 22.5, 5: 67.5, 6: 112.5})
        tt = Turntable(cfg, FakeBackend())
        tt.goto_box(3)

    幂等性：`goto_box` 只发一次脉宽（位置舵机是绝对定位，重复发不会累加，
    2026-09-21 已实测）。
    """

    def __init__(self, config: TurntableConfig, backend: PulseBackend) -> None:
        self.config = config
        self.backend = backend
        self._current_box: int | None = None
        self._locked = False
        # 脉宽覆盖范围只是"上机前自查"信息：360° 角度表（±180°）天然超出
        # [500,2500]µs，此时**不能**在构造期 raise（位置域才是 360° 的正路）。
        try:
            lo, hi = config.coverage()
            pulse_txt = "脉宽范围=[%d,%d]µs" % (lo, hi)
        except TurntableUncalibrated:
            pulse_txt = "脉宽域不可用（超 ±137°，走位置域）"
        plo, phi = config.position_coverage()
        logger.info(
            "[%s] 就绪：零位=%dµs 比例=%.4fµs/度 sign=%+d 角度表=%s %s 位置范围=[%d,%d]",
            config.name, config.zero_pulse_us, config.us_per_degree, config.angle_sign,
            sorted(config.angle_table), pulse_txt, plo, phi,
        )

    # ---- 动作 ----

    def goto_box(self, box_id: int, box_of_current: int | None = None) -> int:
        """转到货格 `box_id` **并等待整定**，返回实际下发的脉宽（µs）。

        要"转了就走、不等它停稳"（转盘与滑台并行）请用 `command_box()`。
        `box_of_current` 只是**记账用**（`current_box`），不影响动作 ——
        位置舵机是绝对定位，不需要知道"现在在哪"就能转到目标。
        """
        pulse = self.command_box(box_id)
        time.sleep(self.config.settle_s)
        logger.info("[%s] 转到货格 %d：角度 %.1f° → %dµs",
                    self.config.name, box_id, self.config.angle_for_box(box_id), pulse)
        return pulse

    def command_box(self, box_id: int) -> int:
        """**只下发脉宽、不等整定**，立刻返回脉宽（µs）。

        给"转盘与滑台并行"的调用方用（2026-09-21 用户裁决：转盘动作计入 15s 失活窗，
        必须与滑台约 12s 的行程**重叠**；用串行版 `goto_box` 会白吃 1~2s 余量）。
        写 pw.txt 是 O(1) 的原子文件替换，真正的转角由常驻 `pi_pw.py`
        （每 0.1s 读一次）+ 舵机在滑台运动期间完成。

        ⚠️ 本方法**不确认转到位** —— 到位判定是调用方的责任
        （见 `rpi/turntable_guard.py`：settle_s 到期 + GPIO17 索引比对）。

        越界脉宽在 `pulse_for_box` 里就 raise（fail-closed），**不会**写进 pw.txt。
        """
        if self._locked:
            raise TurntableLocked("转盘已锁定，拒绝动作（重新标定后需新建实例）")
        pulse = self.config.pulse_for_box(box_id)
        self.backend.set_pulse_us(pulse)
        self._current_box = box_id
        return pulse

    # ---- 位置域动作（2026-11-07：360° 分度用这条路）----

    def command_box_position(self, box_id: int) -> int:
        """**只下发目标位置、不等整定**，返回目标位置值（0~4095）。

        与 `command_box` 的分工：`command_box` 走脉宽域（±137°，旧 PWM 后端），
        本方法走位置域（0~4095 覆盖 360°，ST-3215 总线舵机）。
        越界/未知格在 `pos_for_box` 里就 raise（fail-closed），不会写进舵机。
        """
        if self._locked:
            raise TurntableLocked("转盘已锁定，拒绝动作（重新标定后需新建实例）")
        pos = self.config.pos_for_box(box_id)
        self._emit_position(pos)
        self._current_box = box_id
        return pos

    def goto_box_position(self, box_id: int) -> int:
        """转到货格 `box_id`（位置域）**并等待整定**，返回目标位置值。"""
        pos = self.command_box_position(box_id)
        time.sleep(self.config.settle_s)
        logger.info("[%s] 转到货格 %d：角度 %.1f° → 位置 %d",
                    self.config.name, box_id, self.config.angle_for_box(box_id), pos)
        return pos

    def goto_position(self, pos: int) -> int:
        """直接下发一个位置值（0~4095，标定/测量工具用）。**不做货格映射**。"""
        if self._locked:
            raise TurntableLocked("转盘已锁定，拒绝动作")
        pos = int(pos)
        if not (POS_MIN <= pos <= POS_MAX):
            raise TurntableUncalibrated(
                f"位置 {pos} 超出 [{POS_MIN},{POS_MAX}]（fail-closed，不做 clamp）"
            )
        self._emit_position(pos)
        time.sleep(self.config.settle_s)
        return pos

    def _emit_position(self, pos: int) -> None:
        """优先走后端的位置域接口；只有脉宽后端时退化为位置→脉宽（±137° 内可用）。"""
        setter = getattr(self.backend, "set_position", None)
        if callable(setter):
            setter(int(pos))
            return
        self.backend.set_pulse_us(self.config.pulse_for_position(pos))

    def goto_zero(self) -> int:
        """回零位（角度 0）。"""
        if self._locked:
            raise TurntableLocked("转盘已锁定，拒绝动作")
        pulse = self.config.zero_pulse_us
        self.backend.set_pulse_us(pulse)
        time.sleep(self.config.settle_s)
        logger.info("[%s] 回零位：%dµs", self.config.name, pulse)
        return pulse

    def stop(self) -> None:
        """停止输出（释放）。⚠️ 位置舵机会因此**失去保持力**，只在收工时用。"""
        self.backend.set_pulse_us(PULSE_RELEASE_US)
        logger.info("[%s] 已释放输出", self.config.name)

    def lock(self, reason: str) -> None:
        """进入锁定态：之后所有 `goto_*` 都拒绝（fail-closed）。"""
        self._locked = True
        logger.error("[%s] 进入锁定态：%s", self.config.name, reason)

    @property
    def current_box(self) -> int | None:
        return self._current_box

    def close(self) -> None:
        self.backend.close()


# ---------------------------------------------------------------------------
# 零点自检（现场每次开工前跑一次）
# ---------------------------------------------------------------------------

def zero_check(config: TurntableConfig, backend: PulseBackend, *, prompt_s: float = 0.0) -> int:
    """把转盘发到零位脉宽，返回脉宽值。**判据在操作员眼睛里**：

    指针应当仍停在盘面「线 0」上。若不在 ⇒ 零点已漂（被手动拧过 / 传动打滑）
    ⇒ **重新标定，不要开工**。
    """
    pulse = config.zero_pulse_us
    backend.set_pulse_us(pulse)
    if prompt_s:
        time.sleep(prompt_s)
    logger.info("[%s] 零点自检：已发 %dµs —— 请目视确认指针仍在线 0", config.name, pulse)
    return pulse


# ---------------------------------------------------------------------------
# 离线自检（不接硬件、不发光，可直接 py -3 跑）
# ---------------------------------------------------------------------------

class FakeBackend:
    """把下发的脉宽/位置记进列表，供断言。"""

    def __init__(self) -> None:
        self.pulses: list[int] = []
        self.positions: list[int] = []
        self.position: int = 2048   # 读回值（模拟舵机当前位）
        self.read_fail: bool = False

    def set_pulse_us(self, pulse_us: int) -> None:
        self.pulses.append(pulse_us)

    def set_position(self, pos: int) -> None:
        self.positions.append(int(pos))
        self.position = int(pos)

    def read_pos(self) -> int | None:
        return None if self.read_fail else self.position

    def close(self) -> None:
        return


def _self_check() -> int:
    import sys as _sys

    # Windows 控制台默认 GBK，打不出 'µ' —— 树莓派上是 UTF-8 不受影响。
    # 这里显式切到 UTF-8，保证同一份自检在主机和派上都能跑。
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ok = 0

    # 1) 本次实测标定：线 0 = 1500µs、90° = 655µs、脉宽减小 = 顺时针（取顺时针为正角）
    cfg = TurntableConfig(
        zero_pulse_us=1500,
        us_per_degree=655.0 / 90.0,
        angle_sign=-1,
        angle_table={i + 1: -112.5 + 45.0 * i for i in range(6)},  # 6 格 × 45°，围绕中点对称
        settle_s=0.0,
    )
    lo, hi = cfg.coverage()
    assert 500 <= lo and hi <= 2500, (lo, hi)
    print(f"[1] 6 格 45° 角度表脉宽范围 = [{lo}, {hi}]µs  ✅ 落在 500~2500 内")
    ok += 1

    # 2) 反向验算：线 1（顺时针 90°）应当 ≈ 845µs
    p90 = cfg.pulse_for_angle(90.0)
    assert p90 == 845, p90
    print(f"[2] 顺时针 90° → {p90}µs（实测线 1 = 845µs）  ✅")
    ok += 1

    # 3) 越界必须 raise，不能静默 clamp
    try:
        cfg.pulse_for_angle(180.0)
    except TurntableUncalibrated as exc:
        print(f"[3] 顺时针 180° 被拒（{exc}）  ✅ fail-closed 生效")
        ok += 1
    else:
        raise AssertionError("顺时针 180° 应当越界被拒（需 190µs < 500µs）")

    # 4) 未知货格必须拒
    try:
        cfg.angle_for_box(9)
    except TurntableUncalibrated:
        print("[4] 未知货格 9 被拒  ✅")
        ok += 1
    else:
        raise AssertionError("未知货格应当被拒")

    # 5) 下发 + 幂等（位置舵机不累加）
    be = FakeBackend()
    tt = Turntable(cfg, be)
    tt.goto_zero()
    tt.goto_box(3)
    tt.goto_box(3)
    assert be.pulses == [1500, cfg.pulse_for_box(3), cfg.pulse_for_box(3)], be.pulses
    print(f"[5] 下发序列 = {be.pulses}  ✅（重复同一格只重发同一脉宽，不累加）")
    ok += 1

    # 6) 锁定态拒绝
    tt.lock("自检")
    try:
        tt.goto_box(1)
    except TurntableLocked:
        print("[6] 锁定态拒绝动作  ✅")
        ok += 1
    else:
        raise AssertionError("锁定态应当拒绝")

    # 7) 非法规格必须拒
    for bad in (dict(zero_pulse_us=400), dict(us_per_degree=0.0), dict(angle_sign=0)):
        kw = dict(zero_pulse_us=1500, us_per_degree=1.0, angle_sign=-1)
        kw.update(bad)
        try:
            TurntableConfig(**kw)
        except TurntableUncalibrated:
            pass
        else:
            raise AssertionError(f"非法配置 {bad} 应当被拒")
    print("[7] 非法规格（零位越界 / 比例≤0 / sign 非法）全部被拒  ✅")
    ok += 1

    print(f"\n自检全部通过（{ok}/7）。⚠️ 本自检**不含任何实机验证**。")
    return 0


__all__ = [
    "PULSE_MIN_US",
    "PULSE_MAX_US",
    "PULSE_RELEASE_US",
    "POS_MIN",
    "POS_MAX",
    "DEFAULT_PW_FILE",
    "FakeBackend",
    "PigpioBackend",
    "PulseBackend",
    "PwFileBackend",
    "Turntable",
    "TurntableConfig",
    "TurntableError",
    "TurntableLocked",
    "TurntableUncalibrated",
    "zero_check",
]


if __name__ == "__main__":
    import sys

    sys.exit(_self_check())
