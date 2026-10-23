#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XY 双轴联动台架测试：发 MOVE XY，轮询 STATUS 直到两轴计数归零。

用法：
  python3 move_xy_test.py XDIR0 3200 YDIR0 1600 500
  python3 move_xy_test.py XDIR1 800  YDIR1 400  500 --dry

安全：
  * 需要先 MOTION ARM（本脚本自动发，10s 窗口）
  * 移动预计时间必须 < 8s（给窗口留余量），否则拒绝
  * 轮询 STATUS 的 STEP_REMAIN / STEP_RESULT，超时或故障立即 STEP STOP
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200
MAX_EXPECT_S = 8.0          # 单次联动预计时间上限（10s 窗口留 2s 余量）


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


def status(ser):
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
    # 稳健的 dry 检测：strip 掉可能随 Windows→Linux 传递进来的 \r
    dry = any(a.strip() == "--dry" for a in sys.argv[1:])
    if len(argv) != 5:
        print("用法: python3 move_xy_test.py <XDIR0|XDIR1> <nx> <YDIR0|YDIR1> <ny> <hz>")
        return 2
    xdir, nx, ydir, ny, hz = argv[0].upper(), int(argv[1]), argv[2].upper(), int(argv[3]), int(argv[4])
    if xdir not in ("XDIR0", "XDIR1") or ydir not in ("YDIR0", "YDIR1"):
        print("方向只能 XDIR0/XDIR1/YDIR0/YDIR1")
        return 2
    if nx <= 0 or ny <= 0 or nx > 16000 or ny > 16000:
        print("步数越界 1..16000")
        return 2
    if hz < 10 or hz > 10000:
        print("hz 越界 10..10000")
        return 2

    fx = hz * nx // max(nx, ny)
    fy = hz * ny // max(nx, ny)
    fx = max(fx, 10)
    fy = max(fy, 10)
    tx = nx / float(fx)
    ty = ny / float(fy)

    print("X %s %d步(%.1fmm) @%dHz → %.2fs" % (xdir, nx, nx / 80.0, fx, tx))
    print("Y %s %d步(%.1fmm) @%dHz → %.2fs" % (ydir, ny, ny / 80.0, fy, ty))
    print("合成：%.1f:%.1f = %s" % (nx / 80.0, ny / 80.0,
                                    "直线" if abs(tx - ty) < 0.15 else "非直线(注意)"))
    if max(tx, ty) > MAX_EXPECT_S:
        print("!! 预计 %.2fs 超过 %.1fs 上限（ARM 窗口只有 10s），拒绝执行" % (max(tx, ty), MAX_EXPECT_S))
        return 2
    if dry:
        print("[dry] 不发送")
        return 0

    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    time.sleep(0.4)
    drain(ser, 0.6)

    r = send(ser, "MOTION ARM", 0.8)
    if not any("OK MOTION ARMED" in l for l in r):
        print("!! ARM 失败: %s" % r)
        ser.close()
        return 1
    print("ARM OK")

    cmd = "MOVE XY %s STEPS %d %s STEPS %d HZ %d" % (xdir, nx, ydir, ny, hz)
    r = send(ser, cmd, 0.8)
    print(cmd)
    for l in r:
        print("   " + l)
    if not any("OK MOTION XY STARTING" in l for l in r):
        print("!! 启动失败")
        ser.close()
        return 1

    expect = max(tx, ty)
    t0 = time.time()
    ok = False
    while True:
        time.sleep(0.4)
        el = time.time() - t0
        if el < expect * 1.1:
            continue
        st = status(ser)
        if not st:
            if el > expect + 10.0:
                print("!! 状态读取持续失败")
                break
            continue
        remain = int(st.get("STEP_REMAIN", "0") or 0)
        axis = int(st.get("STEP_AXIS", "0") or 0)
        result = int(st.get("STEP_RESULT", "0") or 0)
        if axis == 0 and remain == 0:
            ok = (result == 1)
            print("完成：用时 %.1fs（预计 %.1fs） STEP_RESULT=%d %s"
                  % (el, expect, result, "OK" if ok else "非成功!"))
            break
        if el > expect + 10.0:
            print("!! 超时 remain=%d" % remain)
            send(ser, "STEP STOP", 0.6)
            break

    ser.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
