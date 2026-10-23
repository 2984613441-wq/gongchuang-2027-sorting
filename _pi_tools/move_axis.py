#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台架分段移动（带 arm 窗口重开 + 到位轮询 + 故障即停）。

为什么分段：
  MOTION ARM 窗口只有 10 秒；生产速度 EC_AXIS_MOVE_FREQUENCY_HZ = 500 Hz，
  500Hz × 10s = 5000 步 = 62.5mm。而 X 全程 90mm = 7200 步（14.4s）、
  Y 全程 92.5mm = 7400 步（14.8s）—— 单条 MOVE 走不完，
  故按 3600 步一段（7.2s @500Hz）切分。

安全：
  * 只允许正方向（DIR0）移动，从 HOME 出发
  * 每段前重新 MOTION ARM
  * 每段后轮询 AXIS，FAULTS != 0 立即中止
  * 累计步数超过 STEPS_PER_MM*目标mm 时拒绝（防止手误多走）

用法：
  python3 move_axis.py X 7200 500      # X 轴走 7200 步，500Hz
  python3 move_axis.py Y 7400 500
  python3 move_axis.py X 7200 500 --dry
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200
SEG_MAX_STEPS = 3600          # 每段最大步数（7.2s @500Hz，留 2.8s 窗口余量）
POLL_S = 0.5


def drain(ser, seconds):
    buf = b""
    end = time.time() + seconds
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.02)
    return buf.decode("ascii", "replace")


def send(ser, cmd, wait=0.8, keep_status=False):
    ser.write((cmd + "\r\n").encode("ascii"))
    ser.flush()
    time.sleep(0.25)
    out = drain(ser, wait)
    lines = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("STATUS") and not keep_status:
            continue
        lines.append(line)
    return lines


def parse_axis(lines):
    """从 AXIS 行解析 FAULTS / STATE / STEP_REMAIN。"""
    for line in lines:
        if line.startswith("AXIS"):
            d = {}
            for tok in line.split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    d[k] = v
            return d
    return {}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    if len(args) != 3:
        print("用法: python3 move_axis.py <X|Y> <steps> <hz> [--dry]")
        return 2
    axis = args[0].upper()
    steps = int(args[1])
    hz = int(args[2])
    if axis not in ("X", "Y"):
        print("轴只能是 X 或 Y")
        return 2
    if not (10 <= hz <= 10000):
        print("hz 越界 10..10000")
        return 2
    if steps <= 0 or steps > 16000:
        print("steps 越界 1..16000（16000 步 = 200mm 是固件上限）")
        return 2

    nseg = (steps + SEG_MAX_STEPS - 1) // SEG_MAX_STEPS
    base = steps // nseg
    rem = steps - base * nseg
    segs = [base + (1 if i < rem else 0) for i in range(nseg)]

    print("轴=%s 总步数=%d (%.1fmm)  速度=%dHz  分 %d 段: %s"
          % (axis, steps, steps / 80.0, hz, nseg, segs))
    for s in segs:
        print("  段 %d 步 = %.1fmm，预计 %.1fs" % (s, s / 80.0, s / float(hz)))
    print()

    if dry:
        print("[dry-run] 未发送任何命令")
        return 0

    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    time.sleep(0.4)
    drain(ser, 0.6)

    done = 0
    for idx, s in enumerate(segs, 1):
        # 1) 开窗口
        lines = send(ser, "MOTION ARM", 0.9)
        armed = any("OK MOTION ARMED" in l for l in lines)
        print("段%d/%d ARM: %s" % (idx, nseg, "OK" if armed else "失败 " + str(lines)))
        if not armed:
            print("!! ARM 失败，中止")
            ser.close()
            return 1

        # 2) 发移动
        cmd = "MOVE %s DIR0 STEPS %d HZ %d" % (axis, s, hz)
        lines = send(ser, cmd, 0.9)
        print("段%d/%d %s" % (idx, nseg, cmd))
        started = any("MOTION_START" in l or "OK" in l for l in lines)
        for l in lines:
            print("      " + l)
        if not started:
            print("!! 移动命令未确认启动，中止")
            ser.close()
            return 1

        # 3) 等它走完
        expect_s = s / float(hz)
        t0 = time.time()
        last = {}
        while True:
            time.sleep(POLL_S)
            ax = parse_axis(send(ser, "AXIS", 0.55))
            last = ax
            faults = int(ax.get("FAULTS", "0") or 0)
            remain = int(ax.get("STEP_REMAIN", "0") or 0)
            state = int(ax.get("STATE", "0") or 0)
            elapsed = time.time() - t0
            if faults != 0:
                print("!! 检测到 FAULTS=%d，立即中止" % faults)
                send(ser, "STEP STOP", 0.6)
                send(ser, "STOP ALL", 0.6)
                ser.close()
                return 1
            if state == 0 and remain == 0 and elapsed > expect_s * 0.5:
                break
            if elapsed > expect_s + 8.0:
                print("!! 超时未到位（remain=%d state=%d），发 STEP STOP" % (remain, state))
                send(ser, "STEP STOP", 0.6)
                ser.close()
                return 1
        done += s
        print("    段%d 完成，用时 %.1fs（预计 %.1fs），累计 %d 步 (%.1fmm)\n"
              % (idx, elapsed, expect_s, done, done / 80.0))

    print("=== 全部完成：%s 轴共走 %d 步 = %.2f mm ===" % (axis, done, done / 80.0))
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
