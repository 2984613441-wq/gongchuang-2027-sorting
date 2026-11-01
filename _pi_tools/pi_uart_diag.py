#!/usr/bin/env python3
"""STM32 串口一键诊断（在树莓派上跑）。

## 为什么需要这个脚本

2026-10-29 22:00 实测：在 Pi 上静默监听 /dev/serial0 5 秒 ⇒ **收到 0 字节**。
板子正常应 1Hz 吐 STATUS 心跳。0 字节意味着：
    · STM32 没上电，或
    · 串口 TX 没接 / 接反，或
    · 波特率不对

本脚本把「怎么确认」变成一条命令，避免每次手工敲。

## 用到的固件命令（来自 ec_diag.c 的 HELP 输出）

    PING     -> OK PONG
    STATUS   -> STATUS SAFE_LOCK=1 ... APP_STATE=xx
    INPUTS   -> INPUTS RAW=xxxx STABLE=xxxx ACTIVE=xxxx
    AXIS     -> AXIS ... FAULT=n ... 以及 STOPCAUSE / WINDOW / EXIT / PREV_STOP
                （**只有 AXIS 会打印 fault_reason**，STATUS 不带）

## 用法（在 Pi 上）

    python3 uart_diag.py                # 默认 /dev/serial0 @115200
    python3 uart_diag.py --port /dev/ttyUSB0 --baud 115200
    python3 uart_diag.py --listen 8     # 只静默监听 8 秒，不发命令

## 判读

    ① 5 秒内一字节都没有        ⇒ 板子没上电 / TX 断路 / 波特率错
    ② 有心跳但 PING 无 PONG     ⇒ RX 方向断路（主机发不进去）
    ③ APP_STATE=FAULT_LOCK      ⇒ 看 AXIS 的 FAULT= 数字（见 FAULT_REASONS）
    ④ APP_STATE=IDLE 等正常态   ⇒ 板子没问题，问题在上层
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    print("❌ 缺 pyserial：pip3 install pyserial")
    sys.exit(1)

# ec_fault_reason_t  ← 真定义在 电控/stm32_logic/include/ec_state_machine.h:24-32
#
# ⚠️ 2026-10-29 22:10 修正：本表旧版（NONE/ESTOP/LIMIT/BARRIER/DRIVER/DESYNC/DEADLINE）
#    是我凭印象编的，**1~5 全错**，会把「EMERGENCY_STOP」误判成「驱动故障」，
#    从而把排查方向从「急停极性/接线」引到「驱动器」——正好背离实际方向。
#    正确枚举如下（已逐字核对头文件）。
FAULT_REASONS = {
    0: "NONE / 无故障",
    1: "RESTART_CONTEXT_UNPROVEN / 重启上下文未证实",
    2: "DEDUP_CONFLICT / 去重冲突（同一任务被重复投递）",
    3: "DEDUP_CAPACITY_EXHAUSTED / 去重容量耗尽",
    4: "EMERGENCY_STOP / 急停（POST 或 HOMING 失败也注入这一条）",
    5: "POWER_PERMISSION_LOST / 上电许可丢失",
    6: "DEADLINE_EXPIRED / 超时（15s 失活窗口）",
}

# 🔴 读到 4 时优先查什么（这一点最容易搞反）
FAULT4_HINT = (
    "FAULT=4 是 EMERGENCY_STOP，不是驱动器故障。\n"
    "      POST（上电自检）与 HOMING（回零）失败都会注入这一个事件\n"
    "      ⇒ 优先查：急停按钮极性/接线、限位开关极性、INPUTS 的 ACTIVE 位\n"
    "      （固件语义：ACTIVE 位=1 表示该输入被触发；raw=1 才表示未触发）"
)

COMMANDS = [
    ("PING", "串口双向连通性"),
    ("STATUS", "总状态（含 APP_STATE）"),
    ("INPUTS", "输入电平（EMERGENCY/限位/障碍）"),
    ("AXIS", "轴诊断（含 FAULT= 锁机原因）"),
]


def read_for(ser, seconds: float) -> bytes:
    """在 seconds 内尽量读，返回原始字节。"""
    t0 = time.time()
    buf = bytearray()
    while time.time() - t0 < seconds:
        waiting = ser.in_waiting
        if waiting:
            buf += ser.read(waiting)
        else:
            time.sleep(0.02)
    return bytes(buf)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--listen", type=float, default=5.0,
                    help="静默监听秒数（不发任何命令）")
    ap.add_argument("--answer", type=float, default=1.5,
                    help="每条命令等回复的秒数")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  STM32 串口诊断  %s @ %d" % (args.port, args.baud))
    print("=" * 70)

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.1)
    except Exception as e:
        print("❌ 打不开串口: %s" % e)
        if "Permission" in str(e) or "denied" in str(e):
            print("   ⇒ 加权限：sudo usermod -aG dialout $USER  （或 sudo 运行）")
        return 1

    try:
        ser.reset_input_buffer()

        # ── ① 静默监听（先看板子自己说不说话）──
        print()
        print("[1] 静默监听 %.1f 秒（不发命令，只收心跳）..." % args.listen)
        raw = read_for(ser, args.listen)
        print("    收到 %d 字节" % len(raw))
        if not raw:
            print()
            print("    🔴 板子完全没说话。可能原因（按概率排）：")
            print("       1. STM32 没上电（电池未接 / 电源开关关）")
            print("       2. 串口 TX 线没接 / 接反 / 松了（Pi RX ← STM32 TX 必须交叉）")
            print("       3. 波特率不对（固件可能是 115200 以外的值）")
            print("       4. 共地没接（GND 不共地会收到垃圾或 0 字节）")
            print()
            print("    ⇒ 先确认上电，再检查 TX/RX 交叉和共地。")
            ser.close()
            return 2
        text = raw.decode("utf-8", errors="replace")
        print("    首行: %s" % text.splitlines()[0][:100] if text.splitlines() else "    (空)")

        # ── ② 逐条命令 ──
        print()
        print("[2] 逐条发命令")
        replies = {}
        for cmd, purpose in COMMANDS:
            ser.reset_input_buffer()
            ser.write((cmd + "\r\n").encode())
            ser.flush()
            resp = read_for(ser, args.answer)
            txt = resp.decode("utf-8", errors="replace").strip()
            replies[cmd] = txt
            print()
            print("  >>> %-8s (%s)" % (cmd, purpose))
            if not txt:
                print("      (无应答)")
            else:
                for ln in txt.splitlines()[:8]:
                    print("      " + ln)

        # ── ③ 判读 ──
        print()
        print("=" * 70)
        print("  判读")
        print("=" * 70)

        ping_ok = "PONG" in replies.get("PING", "")
        print("  串口双向: %s" % ("✅ 通（PING→PONG）" if ping_ok
                                 else "❌ 单向或不通（心跳有但 PING 无回应）"))

        st = replies.get("STATUS", "")
        app_state = ""
        for tok in st.replace("\n", " ").split():
            if tok.startswith("APP_STATE="):
                app_state = tok.split("=", 1)[1]
        if app_state:
            print("  APP_STATE : %s" % app_state)
            if app_state == "FAULT_LOCK":
                print("              🔴 运动被锁。看下面 AXIS 里的 FAULT= 数字")
            else:
                print("              ✅ 非锁机态")
        else:
            print("  APP_STATE : (STATUS 没回或没这字段)")

        ax = replies.get("AXIS", "")
        fault_num = None
        for tok in ax.replace("\n", " ").split():
            if tok.startswith("FAULT="):
                try:
                    fault_num = int(tok.split("=", 1)[1])
                except ValueError:
                    pass
        if fault_num is not None:
            print("  FAULT=    : %d  (%s)" % (fault_num,
                    FAULT_REASONS.get(fault_num, "未知/新增码")))
            if fault_num == 4:
                print("      ⚠️ " + FAULT4_HINT)
        elif app_state == "FAULT_LOCK":
            print("  FAULT=    : 没读到 —— 再发一次 AXIS，或看 STOPCAUSE/EXIT 行")

        inp = replies.get("INPUTS", "")
        if inp:
            print()
            print("  INPUTS 原始:")
            for ln in inp.splitlines()[:3]:
                print("      " + ln)
            print("      ⇒ 固件语义（ec_step_test.c:276）：active = (~raw) & SAFETY_MASK")
            print("         · raw 位 = 1  ⇒ 该输入为**高电平**，即**未触发**")
            print("         · ACTIVE 位 = 1 ⇒ 该输入**已被触发**（低电平有效）")
            print("         ⚠️ 不要把 raw 和 ACTIVE 混着读：raw=0 才是触发状态")

        print()
        print("=" * 70)
        return 0 if ping_ok else 3
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
