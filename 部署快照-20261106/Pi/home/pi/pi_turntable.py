#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""转盘总线舵机驱动 —— ST-3215 + 微雪 Bus Servo Adapter (A) + 树莓派 UART2

━━━ 硬件链路（2026-10-17 实测可用）━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    树莓派 物理27脚 (GPIO0/TXD2) ── 转换板 TX
    树莓派 物理28脚 (GPIO1/RXD2) ── 转换板 RX
    树莓派 GND (30/25/39)        ── 转换板 GND

    ⚠️ 这块转换板是【同名直连】，不是常规的 TX/RX 交叉接法！
       按惯例交叉接过，结果是完全无响应（0 字节）。

━━━ 前提 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. /boot/config.txt 里要有 dtoverlay=uart2  →  产生 /dev/ttyAMA1
    2. 转换板跳帽置于【串口/UART】侧，且有 DC 供电（板载 LED 亮）

━━━ 实测参数 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    舵机 ID  = 1
    波特率    = 1,000,000 (1 Mbps)
    帧格式    = FF FF ID LENGTH INST PARAM... CHECKSUM
    LENGTH   = 参数个数 + 2
    CHECKSUM = ~(ID + LENGTH + INST + PARAM...) & 0xFF
    位置      0~4095 对应 0~360°，每 90° = 1024 计数

    标定位置：A 侧 = 1024，中位 = 2048，B 侧 = 3072

━━━ 用法 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    python3 pi_turntable.py --ping            # 探测舵机是否在线
    python3 pi_turntable.py --read            # 只读当前位置
    python3 pi_turntable.py A                 # 到 A 侧 (1024)   = -90°
    python3 pi_turntable.py B                 # 到 B 侧 (3072)   = +90°
    python3 pi_turntable.py C                 # 回中位 (2048)
    python3 pi_turntable.py 1500              # 到任意位置 0~4095
    python3 pi_turntable.py A --time 3000     # 指定移动耗时 (毫秒，默认 1500)

    环境变量：TURNTABLE_PORT（默认 /dev/ttyAMA1）
              TURNTABLE_BAUD（默认 1000000）
              TURNTABLE_ID  （默认 1）

━━━ 退出码 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    0 成功   1 串口打不开   2 舵机无响应   3 未到位   4 参数错误
"""

from __future__ import annotations

import os
import sys
import time

try:
    import serial
except ImportError:
    sys.stderr.write("缺少 pyserial：pip install pyserial\n")
    raise SystemExit(1)

# ── 配置 ────────────────────────────────────────────────────────────────
PORT = os.environ.get("TURNTABLE_PORT", "/dev/ttyAMA1")
BAUD = int(os.environ.get("TURNTABLE_BAUD", "1000000"))
SID = int(os.environ.get("TURNTABLE_ID", "1"))

POS_A = 1024          # -90°
POS_CENTER = 2048     # 0°
POS_B = 3072          # +90°
POS_MIN, POS_MAX = 0, 4095
COUNTS_PER_DEG = 4096.0 / 360.0     # ≈ 11.38

ADDR_GOAL_POS = 0x2A
ADDR_GOAL_TIME = 0x2C
ADDR_PRESENT_POS = 0x38

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03

DEFAULT_TIME_MS = 1500
ARRIVE_TOL = 20        # 到位判定容差（计数），约 1.8°
POLL_S = 0.05


# ── 协议 ────────────────────────────────────────────────────────────────
def _checksum(body):
    return (~sum(body)) & 0xFF


def _frame(body):
    """body = [ID, LENGTH, INSTRUCTION, *params]"""
    return bytes([0xFF, 0xFF] + list(body) + [_checksum(body)])


class Turntable(object):
    def __init__(self, port=PORT, baud=BAUD, sid=SID, timeout=0.12):
        self.sid = sid
        self.ser = serial.Serial(port, baud, timeout=timeout)

    # -- 底层 ------------------------------------------------------------
    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def _read_packet(self):
        """读一个完整应答包，失败返回 None。"""
        buf = self.ser.read(32)
        i = buf.find(b"\xff\xff")
        if i < 0 or len(buf) < i + 4:
            return None
        pid, ln = buf[i + 2], buf[i + 3]
        need = i + 4 + ln            # 头2 + ID1 + LEN1 + LEN字节(ERR+data+CS)
        if len(buf) < need:
            buf += self.ser.read(need - len(buf))
        if len(buf) < need:
            return None
        return {
            "id": pid,
            "err": buf[i + 4],
            "data": buf[i + 5:i + 4 + ln - 1],   # 去掉末尾 CS
        }

    def _txn(self, body, wait=0.06):
        self.ser.reset_input_buffer()
        self.ser.write(_frame(body))
        self.ser.flush()
        time.sleep(wait)
        return self._read_packet()

    # -- 高层 ------------------------------------------------------------
    def ping(self):
        r = self._txn([self.sid, 2, INST_PING])
        return r is not None and r["id"] == self.sid and r["err"] == 0

    def read_pos(self):
        r = self._txn([self.sid, 4, INST_READ, ADDR_PRESENT_POS, 2])
        if r is None or len(r["data"]) < 2:
            return None
        return r["data"][0] | (r["data"][1] << 8)

    def _write16(self, addr, value):
        v = int(value) & 0xFFFF
        r = self._txn([self.sid, 5, INST_WRITE, addr, v & 0xFF, v >> 8])
        return r is not None and r["err"] == 0

    def goto(self, pos, time_ms=DEFAULT_TIME_MS):
        """移动到一个位置（0~4095），用目标时间限速。返回是否发出成功。"""
        pos = int(pos)
        if not (POS_MIN <= pos <= POS_MAX):
            raise ValueError("位置超范围 0~4095: %d" % pos)
        if not self._write16(ADDR_GOAL_TIME, time_ms):
            return False
        return self._write16(ADDR_GOAL_POS, pos)

    def wait_arrive(self, target, timeout_s=6.0):
        """轮询直到到位（容差 ARRIVE_TOL）。返回 (到位?, 最后位置)。"""
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout_s:
            p = self.read_pos()
            if p is not None:
                last = p
                if abs(p - target) <= ARRIVE_TOL:
                    return True, p
            time.sleep(POLL_S)
        return False, last


# ── CLI ────────────────────────────────────────────────────────────────
def deg_of(pos):
    return pos / COUNTS_PER_DEG


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(__doc__)
        return 0

    time_ms = DEFAULT_TIME_MS
    if "--time" in argv:
        i = argv.index("--time")
        try:
            time_ms = int(argv[i + 1])
        except (IndexError, ValueError):
            sys.stderr.write("--time 需要一个毫秒整数\n")
            return 4
        del argv[i:i + 2]

    try:
        tt = Turntable()
    except Exception as e:
        sys.stderr.write("打开串口失败 %s: %s\n" % (PORT, e))
        return 1

    try:
        if argv[0] == "--ping":
            ok = tt.ping()
            sys.stdout.write("PING %s (ID=%d @ %s)\n" % ("OK" if ok else "无响应", SID, PORT))
            return 0 if ok else 2

        if argv[0] == "--read":
            p = tt.read_pos()
            if p is None:
                sys.stdout.write("读取失败：无响应\n")
                return 2
            sys.stdout.write("当前位置 = %d  (%.1f°)\n" % (p, deg_of(p)))
            return 0

        key = argv[0].upper()
        if key == "A":
            target = POS_A
        elif key == "B":
            target = POS_B
        elif key in ("C", "CENTER", "MID"):
            target = POS_CENTER
        else:
            try:
                target = int(argv[0])
            except ValueError:
                sys.stderr.write("无法识别的参数：%s\n" % argv[0])
                return 4
            if not (POS_MIN <= target <= POS_MAX):
                sys.stderr.write("位置超范围 0~4095：%d\n" % target)
                return 4

        before = tt.read_pos()
        ok = tt.goto(target, time_ms)
        if not ok:
            sys.stdout.write("指令发送失败（舵机无响应）\n")
            return 2
        arrived, after = tt.wait_arrive(target, timeout_s=max(3.0, time_ms / 1000.0 + 4.0))
        sys.stdout.write(
            "目标 %-4d  到位 %-4s  误差 %-4s  角度 %.1f°  %s\n" % (
                target,
                after if after is not None else "?",
                (after - target) if after is not None else "?",
                deg_of(after) if after is not None else -1,
                "OK" if arrived else "未到位",
            )
        )
        return 0 if arrived else 3
    finally:
        tt.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
