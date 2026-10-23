#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精确测速：只测单轴 MOVE 的真实耗时，不做任何人为等待。

为什么需要这个：
  MOVE 的 `HZ f` 参数**基本无效** —— ec_board_stm32.c:start_axis_counted()
  里巡航频率是硬编码 5000Hz（调用 ec_step_profile_plan(..., 200, 5000, 200,
  10000, 10000)），`frequency_hz` 只在规划失败时兜底。
  ⇒ 要测真实速度，必须**忽略 HZ 参数**，只掐表。

测量方法：
  1. 记录发命令的时刻 t0
  2. 高频轮询 STATUS（约 20ms 一次），等 STEP_AXIS==0 且 STEP_REMAIN==0
  3. 记录 t1，用时 = t1 - t0（含串口往返延迟，约 10~30ms，可忽略）
  4. 实测频率 = steps / (t1 - t0)

用法：
  python3 speed_test.py X 2000          # X 轴 +2000 步，测真实速度
  python3 speed_test.py X 2000 --dry
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200
POLL_INTERVAL_S = 0.02      # 20ms 轮询


def drain(ser, seconds):
    buf = b""
    end = time.time() + seconds
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.005)
    return buf.decode("ascii", "replace")


def send_fast(ser, cmd):
    ser.write((cmd + "\r\n").encode("ascii"))
    ser.flush()


def read_status(ser):
    """读一条 STATUS，返回 dict。只读现在缓冲里的内容，不额外等待。"""
    out = drain(ser, 0.03)
    st = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("STATUS"):
            st = line
    if st is None:
        return None
    d = {}
    for tok in st.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    return d


def main():
    argv = [a.strip() for a in sys.argv[1:] if not a.strip().startswith("--")]
    dry = any(a.strip() == "--dry" for a in sys.argv[1:])
    if len(argv) != 2:
        print("用法: python3 speed_test.py <X|Y> <steps> [--dry]")
        return 2
    axis = argv[0].upper()
    steps = int(argv[1])
    if axis not in ("X", "Y"):
        print("轴只能 X 或 Y")
        return 2
    if steps <= 0 or steps > 16000:
        print("步数越界 1..16000")
        return 2

    # 理论预测（按 ec_step_profile_plan 的公式，巡航 5000Hz / 加减速 10000Hz/s）
    START_HZ, CRUISE_HZ, RATE = 200.0, 5000.0, 10000.0
    accel_steps = (CRUISE_HZ ** 2 - START_HZ ** 2) / (2 * RATE)
    ramp_total = 2 * accel_steps
    if steps >= ramp_total:
        # 有匀速段
        pred_t = 2 * (CRUISE_HZ - START_HZ) / RATE + (steps - ramp_total) / CRUISE_HZ
        peak = CRUISE_HZ
    else:
        # 三角形：抬不到巡航速
        peak = ((2 * RATE * RATE * steps + RATE * START_HZ ** 2 + RATE * START_HZ ** 2)
                / (2 * RATE)) ** 0.5
        pred_t = 2 * (peak - START_HZ) / RATE
    print("%s %d 步(%.1fmm)" % (axis, steps, steps / 80.0))
    print("  理论（5000Hz曲线）：峰值 %.0f Hz，预计 %.2f s → %.0f 步/秒"
          % (peak, pred_t, steps / pred_t if pred_t > 0 else 0))
    if dry:
        print("[dry] 不发送")
        return 0

    ser = serial.Serial(PORT, BAUD, timeout=0.05)
    time.sleep(0.4)
    drain(ser, 0.5)

    # ARM
    send_fast(ser, "MOTION ARM")
    time.sleep(0.25)
    r = drain(ser, 0.3)
    if "OK MOTION ARMED" not in r:
        print("!! ARM 失败: %r" % r[:200])
        ser.close()
        return 1

    # 发 MOVE 并开始计时
    t0 = time.perf_counter()
    send_fast(ser, "MOVE %s DIR0 STEPS %d HZ 500" % (axis, steps))
    time.sleep(0.05)
    ack = drain(ser, 0.15)
    if "OK MOTION STARTING" not in ack:
        print("!! MOVE 未被受理: %r" % ack[:200])
        ser.close()
        return 1

    # 高频轮询直到停止；同时请求 STATUS
    t1 = None
    last_req = 0.0
    while True:
        now = time.perf_counter()
        if t1 is not None and now - t1 > 0.4:
            break
        if now - last_req >= POLL_INTERVAL_S:
            send_fast(ser, "STATUS")
            last_req = now
        st = read_status(ser)
        if st is not None:
            axis_state = int(st.get("STEP_AXIS", "0") or 0)
            remain = int(st.get("STEP_REMAIN", "0") or 0)
            if axis_state == 0 and remain == 0:
                if t1 is None:
                    t1 = time.perf_counter()
        if now - t0 > 30.0:
            print("!! 超时")
            ser.close()
            return 1

    elapsed = t1 - t0
    print("  实测：%.3f s  →  %.0f 步/秒  (%.1f mm/s)"
          % (elapsed, steps / elapsed, steps / 80.0 / elapsed))
    print("  相对理论：%.2f 倍%s"
          % (elapsed / pred_t if pred_t > 0 else 0,
             "  ← 接近理论，说明 5000Hz 曲线生效"
             if abs(elapsed / pred_t - 1) < 0.35 else "  ← 与理论不符，需查"))
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
