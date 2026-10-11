#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台架单轴点动观察（通用）：N 次带参数计步移动，每次到位后停 1 秒。

用法： python3 pi_jog.py <X|Y> <0|1> [次数] [步数] [Hz]
例：   python3 pi_jog.py Y 1 4 400 500     # Y 轴 DIR1，4 次 × 400 步（=5mm）

为什么每次都要 MOTION ARM：
  ec_step_test.c:110 —— ec_motion_test_start() 入口即把 motion_armed 置 0，
  arm 是一次性的（EC_MOTION_ARM_WINDOW_MS）。带参数的
  ec_motion_test_start_steps() 同样要求已 arm，故每个点动前必须重发。

命令走 ec_diag.c:486 的 parse_move_steps_command（不是 :498 那两个 strcmp 短形式），
  两种语法都合法，这里用带 STEPS/HZ 的形式以便精确控制距离：
      步数 / 80 steps/mm = 移动毫米数      400 步 = 5mm = 1/8 圈（1 圈 = 3200 步 = 40mm）

注意（别被自己的测法骗）：
  脚本里打印的「到位耗时」偏大 —— 每次轮询都 reset_input_buffer + 读 900 字节
  （超时 0.5s），加上板子自发 1Hz STATUS，单次轮询约 0.85s。
  若多轮耗时几乎相同，那就是轮询周期，不是真实运动时间。

安全：只发 PING/STATUS/MOTION ARM/MOVE。不发生产链路命令。
      检测到 run_chain 在跑会拒绝执行。请先确认小车不在行程端点（X/Y 无硬件限位）。
"""

import re
import subprocess
import sys
import time

PORT = "/dev/serial0"
BAUD = 115200
DWELL_S = 1.0


def main():
    axis = (sys.argv[1] if len(sys.argv) > 1 else "X").upper()
    direction = sys.argv[2] if len(sys.argv) > 2 else "0"
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    steps = int(sys.argv[4]) if len(sys.argv) > 4 else 400
    hz = int(sys.argv[5]) if len(sys.argv) > 5 else 500

    if axis not in ("X", "Y") or direction not in ("0", "1"):
        print("用法： pi_jog.py <X|Y> <0|1> [次数] [步数] [Hz]")
        return 2

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

    move_cmd = "MOVE %s DIR%s STEPS %d HZ %d" % (axis, direction, steps, hz)
    mm_per = steps / 80.0
    try:
        print("=== 目标：%s 轴  DIR%s  ×%d 次  每次 %d 步 = %.2f mm（= %.3f 圈）==="
              % (axis, direction, rounds, steps, mm_per, steps / 3200.0))
        print("命令形态： %s" % move_cmd)
        print("\n=== 基线 ===")
        print("PING   ->", send("PING"))
        print("STATUS ->", status())

        total = 0.0
        for i in range(1, rounds + 1):
            print("\n########## 第 %d/%d 次 ##########" % (i, rounds))
            print("MOTION ARM ->", send("MOTION ARM", 0.5))
            print("%-10s ->" % move_cmd.split()[0], send(move_cmd, 0.3))
            print("  紧随 STATUS ->", status())

            t0 = time.time()
            while time.time() - t0 < 8.0:
                rem, res, app = status()
                if rem == 0:
                    break
            total += mm_per
            print("  归零用时 %.2f s（含轮询开销，勿当真实运动时间）  累计 %.1f mm"
                  % (time.time() - t0, total))

            if i < rounds:
                print("  ……停留 %.1f 秒（观察）" % DWELL_S)
                time.sleep(DWELL_S)

        print("\n=== 收尾 ===")
        print("AXIS   ->", send("AXIS", 0.6))
        print("STATUS ->", status())
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
