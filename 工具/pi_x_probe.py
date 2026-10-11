#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X/Y 正方向 10mm 试探（只走"离开最里角"的方向，绝不通往限位端）。

前提（已由用户确认）：
  · 最里角 = 负 X 极限 ∩ 负 Y 极限 = HOME(-950,-975)，滑台现在停在这里。
  · X 正方向 = DIR0，Y 正方向 = DIR1（ec_motion_plan.h:44-45）。
  => 从最里角走 DIR0 / DIR1 就是"往外走"，安全。

顺序：
  0) 等板子应答
  1) 先读 AXIS 锁存（复位不清，只有断电清）—— 上一轮方框测试的故障码
  2) MOVE X DIR0 STEPS 800 HZ 1000  = 10mm，慢速，等于既往标定用的命令形式
  3) MOVE Y DIR1 STEPS 800 HZ 1000  = 10mm
  4) 再读 AXIS / STATUS

目的：分辨「X 完全不动、只嗡嗡」（电/机械故障）vs「X 能走但这方向是往限位端」
      （方向或原点符号错）。因为现在方向已排除，这一跑只看 X 到底还能不能走。
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
        print("X 板子 40s 内无应答 —— 供电/串口/复位 三选一，先别动电机")
        s.close()
        return 1

    print("\n=== 1) 上一轮故障锁存（复位不清）===")
    print(send("AXIS", 0.8) or "(空)")
    print(send("STATUS", 0.4) or "(空)")

    print("\n=== 2) 正方向 10mm 试探（都是'离开最里角'的方向）===")
    legs = [("X", "0", "X DIR0 = X 正方向"), ("Y", "1", "Y DIR1 = Y 正方向")]
    for axis, d, label in legs:
        cmd = "MOVE %s DIR%s STEPS %d HZ 1000" % (axis, d, STEPS)
        print("\n--- %s （10mm）---" % label)
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
            print("  !! 本段全程无应答 —— 板子又哑了")
        time.sleep(1.0)

    print("\n=== 3) 收尾 ===")
    print(send("AXIS", 0.8) or "(空)")
    s.close()
    print("\n【请回答】X 这次动了没有？往哪边？Y 呢？")
    return 0


if __name__ == "__main__":
    sys.exit(main())
