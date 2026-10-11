#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向复验：每轴各走 10mm 来回（DIR0 去 / DIR1 回，再 DIR1 去 / DIR0 回）。

目的：实机确认 X/Y 的 DIR0、DIR1 到底往哪边走。
      之前 pi_square.py 100mm 出现异响，怀疑方向约定反了或起点不在最里角。

安全：
  · 每段只有 800 步 = 10mm @80步/mm，慢速 500Hz，走错也只是 10mm 顶死；
  · 跑之前请把滑台推到行程**中间**，两端都留出余量；
  · 先读 AXIS 锁存（上一轮方框测试的故障记录），再动电机。

用法： python3 pi_dir_test.py
"""

import re
import subprocess
import sys
import time

PORT = "/dev/serial0"
BAUD = 115200
STEPS = 800          # 10mm


def main():
    if subprocess.run(["pgrep", "-f", "run_chain"],
                      capture_output=True).stdout.strip():
        print("ABORT: run_chain 正在运行 —— 拒绝占用 /dev/serial0")
        return 2

    import serial
    s = serial.Serial(PORT, BAUD, timeout=0.5)
    time.sleep(0.3)

    def send(cmd, wait=0.4):
        s.reset_input_buffer()
        s.write((cmd + "\r\n").encode("ascii"))
        time.sleep(wait)
        return s.read(900).decode("ascii", "replace").strip()

    def status():
        txt = send("STATUS", 0.3)
        m = re.search(r"STEP_REMAIN=(\d+)", txt)
        r = re.search(r"STEP_RESULT=(\d+)", txt)
        a = re.search(r"APP_STATE=(\S+)", txt)
        return (int(m.group(1)) if m else -1,
                int(r.group(1)) if r else -1,
                a.group(1) if a else "?")

    # ---- 0) 等板子应答 ----
    print("=== 0) 等板子应答（最多 40s）===")
    ok = False
    for i in range(1, 17):
        reply = send("PING", 0.5)
        if reply:
            ok = True
            print("  第 %d 次有应答：%s" % (i, reply))
            break
        print("  第 %d 次无应答（%.1fs）" % (i, i * 2.5))
    if not ok:
        print("X 板子 40s 内始终无应答 —— 请按复位键/查供电 后再跑")
        s.close()
        return 1

    # ---- 1) 先读上一轮故障锁存（复位不清，只有断电才清）----
    print("\n=== 1) 上一轮故障锁存 AXIS ===")
    print(send("AXIS", 0.8) or "(空)")

    # ---- 2) 四段 10mm ----
    print("\n=== 2) 四段 10mm 方向复验 ===")
    legs = [
        ("X", "0", "X DIR0 —— 请记：往哪边"),
        ("X", "1", "X DIR1 —— 请记：往哪边"),
        ("Y", "1", "Y DIR1 —— 请记：往哪边"),
        ("Y", "0", "Y DIR0 —— 请记：往哪边"),
    ]
    for i, (axis, d, label) in enumerate(legs, 1):
        cmd = "MOVE %s DIR%s STEPS %d HZ 500" % (axis, d, STEPS)
        print("\n--- 第 %d/4 段  %s （10mm）---" % (i, label))
        print("  MOTION ARM ->", send("MOTION ARM", 0.5) or "(空)")
        print("  %s ->" % cmd, send(cmd, 0.3) or "(空)")
        t0 = time.time()
        rem, res, app = -1, -1, "?"
        while time.time() - t0 < 8.0:
            rem, res, app = status()
            if rem == 0:
                break
        print("  结束 %.2fs  STEP_REMAIN=%d STEP_RESULT=%d APP=%s"
              % (time.time() - t0, rem, res, app))
        if rem == -1:
            print("  !! 本段全程板子无应答 —— 板子可能已经卡死")
            break
        time.sleep(0.8)

    print("\n=== 3) 收尾 AXIS ===")
    print(send("AXIS", 0.8) or "(空)")
    print(send("STATUS", 0.4) or "(空)")
    s.close()

    print("\n【请回答】四段各自实际往哪边走了？（可直接说“X 的 DIR0 往左/往右”）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
