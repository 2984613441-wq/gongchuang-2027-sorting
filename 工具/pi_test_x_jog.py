#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X 轴点动观察：4 次 MOVE X DIR0 STEPS 400 HZ 500，每次到位后停 1 秒。

为什么每次都要 MOTION ARM：
  ec_step_test.c:110 —— ec_motion_test_start() 入口就把 motion_armed 置 0，
  arm 是一次性的（窗口 EC_MOTION_ARM_WINDOW_MS）。带参数的
  ec_motion_test_start_steps() 同样要求已 arm，所以每个点动前都要重发。

完成判据：轮询 STATUS 的 STEP_REMAIN（ec_diag.c:396-398 暴露的是
  ec_motion_test_step_remaining()，正覆盖本条台架路径）。
  先等它由 0 变正（动作开始），再等它回到 0（到位），
  然后才真正 dwell 1 秒 —— 这样「停 1 秒」是到位后的静置，不是把运动时间算进去。

安全：只发 PING/STATUS/MOTION ARM/MOVE，不发任何生产链路命令。
      400 步 = 5mm（80 steps/mm），4 次共前进约 20mm。检测到 run_chain 在跑会拒绝。
"""

import re
import subprocess
import sys
import time

PORT = "/dev/serial0"
BAUD = 115200
STEP_COUNT = 400      # 400 / 80 = 5 mm = 1/8 圈
FREQ_HZ = 500
ROUNDS = 4
DWELL_S = 1.0


def main():
    if subprocess.run(["pgrep", "-f", "run_chain"], capture_output=True).stdout.strip():
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
        txt = send("STATUS", 0.35)
        m = re.search(r"STEP_REMAIN=(\d+)", txt)
        r = re.search(r"STEP_RESULT=(\d+)", txt)
        a = re.search(r"APP_STATE=(\S+)", txt)
        return (int(m.group(1)) if m else -1,
                int(r.group(1)) if r else -1,
                a.group(1) if a else "?")

    try:
        print("=== 基线 ===")
        print("PING   ->", send("PING"))
        print("STATUS ->", status())

        total_mm = 0.0
        for i in range(1, ROUNDS + 1):
            print("\n########## 第 %d/%d 次 ##########" % (i, ROUNDS))
            print("MOTION ARM ->", send("MOTION ARM", 0.5))
            print("MOVE       ->", send(
                "MOVE X DIR0 STEPS %d HZ %d" % (STEP_COUNT, FREQ_HZ), 0.3))

            # 等动作开始（STEP_REMAIN 由 0 变正）
            t0 = time.time()
            started = False
            while time.time() - t0 < 3.0:
                rem, res, _ = status()
                if rem > 0:
                    started = True
                    break
            if not started:
                print("  ⚠️ 3 秒内 STEP_REMAIN 未变正 —— 动作可能没起来")
                print("  STATUS ->", status())

            # 等到位（STEP_REMAIN 回到 0）
            while time.time() - t0 < 8.0:
                rem, res, app = status()
                if rem == 0:
                    break
            moved = time.time() - t0
            total_mm += STEP_COUNT / 80.0
            print("  到位耗时 %.2f s   累计前进约 %.1f mm   STATUS -> %s"
                  % (moved, total_mm, (rem, res, app)))

            if i < ROUNDS:
                print("  ……停留 %.1f 秒（观察）" % DWELL_S)
                time.sleep(DWELL_S)

        print("\n=== 收尾 ===")
        print("AXIS ->", send("AXIS", 0.6))
        print("STATUS ->", status())
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
