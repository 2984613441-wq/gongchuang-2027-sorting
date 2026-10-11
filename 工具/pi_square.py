#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正方形轨迹测试：X+ → Y+ → X− → Y−，每边 50mm，最后应回到起点。

用法： python3 pi_square.py [边长mm] [每边步数_可选]
默认边长 50mm（= 4000 步 @80 步/mm = 1.25 圈）。

为什么要这样测：
  · 一次同时暴露 X、Y 两轴的 50mm 精度；
  · 四条腿首尾相接 —— **如果最后没回到起点，就是丢步**（去回不能抵消）；
  · 方向约定：X 正方向 = DIR0，Y 正方向 = DIR1（均已实机验证，
    见 ec_motion_plan.h:44-45）。

安全：只发 PING/STATUS/MOTION ARM/MOVE。每条腿前重发 MOTION ARM
      （ec_step_test.c:110 一次性消费）。请在滑台远离两端时运行。
"""

import re
import subprocess
import sys
import time

PORT = "/dev/serial0"
BAUD = 115200
STEPS_PER_MM = 80


def main():
    side_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 50.0
    steps = int(round(side_mm * STEPS_PER_MM))

    if subprocess.run(["pgrep", "-f", "run_chain"], capture_output=True).stdout.strip():
        print("ABORT: run_chain 正在运行 —— 拒绝占用 /dev/serial0")
        return 2

    import serial
    s = serial.Serial(PORT, BAUD, timeout=0.1)
    time.sleep(0.3)

    def send(cmd, wait=0.15):
        s.reset_input_buffer()
        s.write((cmd + "\r\n").encode("ascii"))
        time.sleep(wait)
        return s.read(2000).decode("ascii", "replace").strip()

    def remain():
        """快读状态。timeout=0.1 且发完立刻收，否则第一次看到状态时运动已经结束。"""
        s.reset_input_buffer()
        s.write(b"STATUS\r\n")
        deadline = time.time() + 0.15
        buf = b""
        while time.time() < deadline:
            chunk = s.read(2048)
            if chunk:
                buf += chunk
                if b"APP_STATE" in buf:
                    break
        txt = buf.decode("ascii", "replace")
        m = re.search(r"STEP_REMAIN=(\d+)", txt)
        r = re.search(r"STEP_RESULT=(\d+)", txt)
        return (int(m.group(1)) if m else -1, int(r.group(1)) if r else -1)

    def wait_done(timeout=20.0):
        """必须【先看到 STEP_REMAIN>0】才认 =0。

        2026-09-19 修：旧写法 `if rem == 0: break` 会拿到上一动残留的 0，
        于是在上一动还没走完时就发下一条 MOVE —— 正方形测试本身就是靠
        "四条腿首尾相接"来验丢步的，判据坏了这个验证也就废了。
        """
        t0 = time.time()
        started = False
        res = -1
        while time.time() - t0 < timeout:
            rem, res = remain()
            if rem > 0:
                started = True
            if started and rem == 0:
                return time.time() - t0, res, True
            if not started and time.time() - t0 > 3.0:
                return time.time() - t0, res, False
            time.sleep(0.05)
        return time.time() - t0, res, False

    legs = [
        ("X", "0", "X+ 第一条边"),
        ("Y", "1", "Y+ 第二条边"),
        ("X", "1", "X- 第三条边"),
        ("Y", "0", "Y- 第四条边（应回到起点）"),
    ]

    print("=== 正方形：每边 %.1f mm = %d 步 = %.3f 圈 ===" % (side_mm, steps, steps / 3200.0))
    print("PING ->", send("PING"))
    bad = 0
    try:
        for i, (axis, d, label) in enumerate(legs, 1):
            cmd = "MOVE %s DIR%s STEPS %d HZ 500" % (axis, d, steps)
            print("\n--- 第 %d/4 腿  %s ---" % (i, label))
            print("MOTION ARM ->", send("MOTION ARM", 0.25))
            print("%s ->" % cmd, send(cmd, 0.12))
            dt, res, ok = wait_done()
            print("  到位 %.2fs（含轮询开销）  STEP_RESULT=%d  %s"
                  % (dt, res, "OK" if ok else "!! 没看到运动，这条腿可能没执行"))
            if not ok or res != 1:
                bad += 1
            if i < len(legs):
                time.sleep(1.0)
        print("\n=== 收尾 ===")
        print("AXIS ->", send("AXIS", 0.6))
    finally:
        s.close()

    if bad:
        print("\n!! 有 %d 条腿没正常执行 —— 本次结果作废，不要据此判断丢步" % bad)
        return 3
    print("\n【请看】四点：① 四条边是否各 50mm ② 四个角是否直角"
          " ③ 最后是否回到起点（没回=丢步）④ 是否有异响/抖动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
