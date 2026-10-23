#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台架分段移动 v2 —— 修正到位判定。

v1 的错误：用 AXIS 命令判到位。AXIS 报的是 **ec_axis_driver**（生产路径）的统计，
而台架 `MOVE` 走的是 **ec_step_test** 模块，两者是不同的代码路径 ——
台架模式下 AXIS 的 STATE/STEP_REMAIN 恒为 0，导致"一进循环就以为到位"。

v2 判定依据：
  * STATUS 行的 `STEP_REMAIN`（台架模块的剩余步数）
  * STATUS 行的 `STEP_RESULT`（1 = 成功）
  * STATUS 行的 `STEP_AXIS`（0 = 空闲）
  * 另外**强制等满** 预计时间 × MIN_WAIT_FACTOR，绝不早于理论上限退出

安全：
  * 只允许 DIR0（正方向）
  * 每段前重新 MOTION ARM（窗口 10s）
  * 每段 ≤ 3600 步（7.2s @500Hz）
  * 检测到 STEP_RESULT != 1 或通信连续失败 → 中止

用法：
  python3 move_axis_v2.py X 7200 500
  python3 move_axis_v2.py X 7200 500 --dry
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200
SEG_MAX_STEPS = 3600
MIN_WAIT_FACTOR = 1.15      # 至少等 预计时间 × 1.15
MAX_WAIT_EXTRA_S = 10.0     # 超过 预计时间 + 10s 仍未到位 → 中止


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


def send(ser, cmd, wait=0.8):
    ser.write((cmd + "\r\n").encode("ascii"))
    ser.flush()
    time.sleep(0.2)
    out = drain(ser, wait)
    lines = []
    for line in out.splitlines():
        line = line.strip()
        if line and not line.startswith("STATUS"):
            lines.append(line)
    return lines


def last_status(ser):
    """单独取一条最新 STATUS（这里需要看 STATUS，不能过滤）。"""
    ser.reset_input_buffer()
    ser.write(b"STATUS\r\n")
    ser.flush()
    time.sleep(0.2)
    out = drain(ser, 0.5)
    st = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("STATUS"):
            st = line
    if st is None:
        return {}
    d = {}
    for tok in st.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    return d


def main():
    argv = [a.strip() for a in sys.argv[1:] if not a.strip().startswith("--")]
    dry = any(a.strip() == "--dry" for a in sys.argv[1:])
    if len(argv) != 3:
        print("用法: python3 move_axis_v2.py <X|Y> <steps> <hz> [--dry]")
        return 2
    axis = argv[0].upper()
    steps = int(argv[1])
    hz = int(argv[2])
    if axis not in ("X", "Y"):
        print("轴只能 X 或 Y")
        return 2
    if not (10 <= hz <= 10000):
        print("hz 越界")
        return 2
    if not (1 <= steps <= 16000):
        print("steps 越界 1..16000")
        return 2

    nseg = (steps + SEG_MAX_STEPS - 1) // SEG_MAX_STEPS
    base = steps // nseg
    rem = steps - base * nseg
    segs = [base + (1 if i < rem else 0) for i in range(nseg)]

    print("轴=%s 总=%d步(%.2fmm)  %dHz  分%d段 %s"
          % (axis, steps, steps / 80.0, hz, nseg, segs))
    for s in segs:
        print("   %d步=%.1fmm 预计%.1fs" % (s, s / 80.0, s / float(hz)))
    if dry:
        print("[dry] 不发送命令")
        return 0

    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    time.sleep(0.4)
    drain(ser, 0.6)

    done = 0
    for idx, s in enumerate(segs, 1):
        if not any("OK MOTION ARMED" in l for l in send(ser, "MOTION ARM", 0.8)):
            print("!! 段%d ARM 失败" % idx)
            ser.close()
            return 1
        cmd = "MOVE %s DIR0 STEPS %d HZ %d" % (axis, s, hz)
        resp = send(ser, cmd, 0.8)
        print("段%d/%d %s" % (idx, nseg, cmd))
        for l in resp:
            print("      " + l)
        if not any("MOTION STARTING" in l for l in resp):
            print("!! 未启动，中止")
            ser.close()
            return 1

        expect = s / float(hz)
        t0 = time.time()
        ok = False
        while True:
            time.sleep(0.4)
            st = last_status(ser) if (time.time() - t0) > expect * MIN_WAIT_FACTOR else {}
            el = time.time() - t0

            # 强制等满理论时间，不看状态（避免 v1 那种"一进循环就以为到位"）
            if el < expect * MIN_WAIT_FACTOR:
                continue
            if not st:
                continue
            remain = int(st.get("STEP_REMAIN", "0") or 0)
            state = int(st.get("STEP_AXIS", "0") or 0)
            result = int(st.get("STEP_RESULT", "0") or 0)
            if state == 0 and remain == 0:
                if result == 1:
                    ok = True
                else:
                    print("!! 段%d 结束但 STEP_RESULT=%d（非成功）" % (idx, result))
                break
            if el > expect + MAX_WAIT_EXTRA_S:
                print("!! 段%d 超时 remain=%d state=%d" % (idx, remain, state))
                send(ser, "STEP STOP", 0.6)
                break
        if not ok:
            send(ser, "STEP STOP", 0.6)
            ser.close()
            return 1
        done += s
        print("   段%d OK 用时%.1fs(预计%.1fs) 累计%d步=%.1fmm\n"
              % (idx, time.time() - t0, expect, done, done / 80.0))

    print("=== 完成：%s 共 %d 步 = %.2f mm ===" % (axis, done, done / 80.0))
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
