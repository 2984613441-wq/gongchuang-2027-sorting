#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z 舵机台架（树莓派侧）—— 用树莓派自己的串口给 STM32 发 SERVO 命令。

为什么存在：SERVO 命令走 USART2 = PA2/PA3，和树莓派链路是【同一条物理线】
（ec_diag_port_write 与 ec_board_uart_transmit 都用 huart2）。所以不拔线也能测：
树莓派直接往串口写 ASCII 即可 —— App/Src/ec_app.c:576-578 的入口分流是
"收到 0xA5 开头 → 走二进制协议；否则 → 交给 ASCII 诊断"。

安全约束（照 docs/plans-2026-09-16/03-Z舵机脉宽重测-测试SOP-2026-09-16.md）：
  * 白名单只有 7 档，本脚本【拒绝任何其他值】
  * 一次只发一个值；每个值都重新 ARM（ARM 窗口 10 s，本脚本连续发不会超）
  * 绝不扫频 / 连发 / 宏
  * 每条命令都读回显；读不到就明确报错，不静默继续

用法（在树莓派上）：
    python3 pi_servo_bench.py --selftest            # 不碰串口，自检
    python3 pi_servo_bench.py                       # 自动找串口
    python3 pi_servo_bench.py --port /dev/serial0
    python3 pi_servo_bench.py --port /dev/serial0 --dry-run   # 只打印要发什么，不开串口

⚠️ 跑本脚本前必须确认：run_chain.py 没在跑（它会抢串口且说二进制协议）；
   舵盘已拆、X/Y 动力电已断、急停能真正切断舵机动力、手不离急停。
"""
from __future__ import annotations

import argparse
import sys
import time

# 固件白名单，逐字匹配（App/Src/ec_diag.c:52-59 + ec_servo_test.c:21-30）
WHITELIST = (1000, 1100, 1200, 1300, 1500, 1700, 1900)
FIRST_SHOT = 1500
COMMON_PORTS = ("/dev/serial0", "/dev/ttyAMA0", "/dev/ttyS0", "/dev/ttyUSB0", "/dev/ttyACM0")


def reconfigure_stdout() -> None:
    """把 stdout/stderr 钉成 UTF-8。

    必要性（实测）：树莓派 Lite 版 locale 常是 POSIX/C，Windows 中文控制台是 GBK，
    两者都会在 print("⚠️") 上抛 UnicodeEncodeError 直接崩。
    同仓库 工具/pi_screen_probe.py 用的是同一种处理。
    """
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def cmd_arm() -> str:
    return "SERVO ARM"


def cmd_pulse(us: int) -> str:
    return "SERVO PB10 P%d" % us


def check_pulse(us: int) -> bool:
    """白名单校验 —— 唯一的把关点，别在别处绕过它。"""
    return us in WHITELIST


def find_port() -> str | None:
    try:
        import serial.tools.list_ports as lp
        for p in lp.comports():
            if p.device in COMMON_PORTS:
                return p.device
        ports = list(lp.comports())
        if ports:
            return ports[0].device
    except Exception as exc:  # noqa: BLE001
        print("  枚举串口失败：%s" % exc)
    import os
    for dev in COMMON_PORTS:
        if os.path.exists(dev):
            return dev
    return None


def read_for(ser, seconds: float = 0.6) -> str:
    deadline = time.time() + seconds
    buf = bytearray()
    while time.time() < deadline:
        try:
            n = ser.in_waiting
        except Exception:  # noqa: BLE001
            n = 0
        if n:
            buf += ser.read(n)
            deadline = time.time() + 0.25  # 收到东西就再等一小会
        else:
            time.sleep(0.03)
    try:
        return buf.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return repr(bytes(buf))


def send(ser, line: str, wait: float = 0.6) -> str:
    print("  → 发送: %s" % line)
    ser.write((line + "\r\n").encode("ascii"))
    ser.flush()
    resp = read_for(ser, wait)
    for row in resp.replace("\r", "").split("\n"):
        row = row.strip()
        if row:
            print("  ← %s" % row)
    if not resp.strip():
        print("  ← (无回显)")
    return resp


def do_one(ser, us: int, gap_s: float = 10.0) -> None:
    """发一个脉宽：先 ARM 再发值（两步必须落在 10 s 窗口内，所以连续发）。"""
    print("\n--- 脉宽 %d µs ---" % us)
    r1 = send(ser, cmd_arm())
    if "ARMED" not in r1:
        print("  !! 未取到 ARM 授权，本值中止。原文见上（常见：ERR SERVO_INHIBITED_OR_BUSY = 急停被拉低或台架忙）")
        return
    r2 = send(ser, cmd_pulse(us))
    if "STARTING" not in r2:
        print("  !! 未开始输出，本值中止。原文见上（常见：ERR SERVO_NOT_ARMED_INHIBITED_OR_BUSY）")
        return
    print("  ⏱ 2 秒后自动停 PWM —— 现在观察：转动方向 / 是否憋死(嗡鸣·发热·电流) / 位置")
    print("  间隔 ≥%.0f s 再发下一个（SOP §5 要求）" % gap_s)


def selftest() -> int:
    ok = True

    def chk(name, cond):
        nonlocal ok
        print("  [%s] %s" % ("OK" if cond else "FAIL", name))
        ok = ok and cond

    chk("白名单 7 档且含 1500", WHITELIST == (1000, 1100, 1200, 1300, 1500, 1700, 1900))
    chk("不含 1400（固件也不认）", not check_pulse(1400))
    chk("不含 1600", not check_pulse(1600))
    chk("不含 1800", not check_pulse(1800))
    chk("含 1500", check_pulse(1500))
    chk("含 1900", check_pulse(1900))
    chk("命令串正确", cmd_pulse(1500) == "SERVO PB10 P1500")
    chk("ARM 命令串正确", cmd_arm() == "SERVO ARM")
    chk("首法必须是 1500", FIRST_SHOT == 1500)
    print("\n自检：%s" % ("全部通过" if ok else "有失败项"))
    return 0 if ok else 1


def main() -> int:
    reconfigure_stdout()
    ap = argparse.ArgumentParser(description="Z 舵机台架（树莓派侧，走 USART2 的 ASCII 诊断）")
    ap.add_argument("--port", default=None, help="串口设备，如 /dev/serial0；不给则自动找")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--selftest", action="store_true", help="不碰串口，只跑自检")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要发送的内容，不开串口")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    print("=" * 60)
    print("Z 舵机台架（树莓派侧） —— 走 USART2 的 ASCII 诊断命令")
    print("=" * 60)
    print("白名单: %s" % " ".join(str(v) for v in WHITELIST))
    print()
    print("⚠️ 发之前请确认（SOP §1/§2）：")
    print("   1. 舵盘已拆（空载）")
    print("   2. X/Y 动力电已断（拔 A4988 VMOT 或电机线）")
    print("   3. 舵机独立 5–6V ≥3A 供电，GND 与 STM32 共地")
    print("   4. 急停能真正切断舵机动力（量过 5–6V → 0V）")
    print("   5. 一只手全程放在急停上")
    print("   6. run_chain.py 没在跑")
    print()
    try:
        input("确认以上全部满足后按回车继续（Ctrl-C 退出）... ")
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130
    print()

    if args.dry_run:
        print("\n--dry-run：不开串口、也不需要串口设备。实际会依次发送：")
        print("  %s" % cmd_arm())
        print("  %s" % cmd_pulse(FIRST_SHOT))
        return 0

    port = args.port or find_port()
    if not port:
        print("找不到串口。先跑 `ls -l /dev/serial*` 和 "
              "`python3 -c \"import serial.tools.list_ports as p;print(list(p.comports()))\"`，"
              "再用 --port 指定。")
        return 2
    print("串口: %s  %d 8N1" % (port, args.baud))

    try:
        import serial
    except ImportError:
        print("缺 pyserial。树莓派上装：sudo apt install python3-serial  （或 pip3 install pyserial）")
        return 2

    try:
        ser = serial.Serial(port, args.baud, timeout=0.2)
    except Exception as exc:  # noqa: BLE001
        print("打不开 %s：%s" % (port, exc))
        print("  常见原因：run_chain.py 正占着这个口 / 权限不足（试试 sudo 或把用户加进 dialout 组）")
        return 2

    print("已打开。第一发固定 P%d（中位基线）。\n" % FIRST_SHOT)
    with ser:
        # 先看一眼上电自检与 STATUS（SOP §7.3）
        print("先听 3 秒，确认能看到 BOOT 与 STATUS：")
        boot = read_for(ser, 3.0)
        for row in boot.replace("\r", "").split("\n"):
            if row.strip():
                print("  ← %s" % row.strip())
        if "STATUS" not in boot:
            print("  !! 3 秒内没看到 STATUS。SOP §7.3 要求先解决这个再继续。")
            print("     若你确信固件没问题，仍想继续，自己判断；否则 Ctrl-C 退出。")

        try:
            do_one(ser, FIRST_SHOT)
            while True:
                try:
                    raw = input("\n下一个脉宽（回车=重发 1500，q=退出，l=看当前 STATUS）: ").strip()
                except EOFError:
                    break
                if raw.lower() in ("q", "quit", "exit"):
                    break
                if raw.lower() in ("l", "status"):
                    send(ser, "STATUS")
                    continue
                if raw == "":
                    us = FIRST_SHOT
                else:
                    try:
                        us = int(raw)
                    except ValueError:
                        print("  不是数字，忽略。")
                        continue
                if not check_pulse(us):
                    print("  !! %d 不在白名单 %s 内 —— 固件也不认，拒绝发送。" % (us, WHITELIST))
                    continue
                do_one(ser, us)
        except KeyboardInterrupt:
            print("\n\n中断。建议发一次 SERVO STOP 收尾。")
            try:
                send(ser, "SERVO STOP")
            except Exception:  # noqa: BLE001
                pass

    print("\n结束。收尾（SOP §9.3）：拆测试电源/临时线，装回舵盘与机构负载。")
    print("要回生产固件：烧 diankongv1_prod_20260916.hex（或让 DSH 重建，4 秒）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
