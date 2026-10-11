#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z 轴/夹爪舵机脉宽扫描观察 —— 逐档发脉宽，每档停 3 秒供目视。

用途：填充 电控/calibration-logs/step1-servo-calibration.txt 里那张空白标定表，
      并核对 ec_axis_driver.h 现行值（OPEN=1100 / CLOSE=1900）是否与实际机构一致。

为什么每档都要 SERVO ARM：
  ec_servo_test.c:69-70 —— 「An authorization is single-use, including rejected
  start attempts」，即 SERVO ARM 只能用一次。
为什么发完会自动停：
  ec_servo_test.c:102-107 —— 到 EC_SERVO_RUN_MS（约 2s）就 ec_servo_port_stop()。
  对位置舵机无妨（到位后自锁），但要观察"持续夹持"就得连续重发。

只用台架 SERVO 命令，不发生产链路命令；检测到 run_chain 在跑会拒绝执行。
"""

import re
import subprocess
import sys
import time

PORT = "/dev/serial0"
BAUD = 115200
DWELL_S = 3.0

# 与 ec_diag.c 的 servo_pulse_from_command 命令表完全一致
# （且必须同时被 ec_servo_test.c 的 is_allowed_pulse 放行 —— 两处是独立的闸）
# 900/950 为 2026-09-19 新增：探 P1000 之上的"完全张开"端点。
# ⚠️ 越低越贴近机械端点：听到持续嗡嗡声/异响立刻按 Ctrl-C 并 SERVO STOP。
SWEEP = [900, 950, 1000, 1100, 1200, 1300, 1500, 1700, 1900]


def main():
    # 支持命令行指定档位： python3 pi_servo_sweep.py 1000 950 900 1000
    sweep = [int(a) for a in sys.argv[1:]] or SWEEP

    if subprocess.run(["pgrep", "-f", "run_chain"], capture_output=True).stdout.strip():
        print("ABORT: run_chain 正在运行 —— 拒绝占用 /dev/serial0")
        return 2

    import serial
    s = serial.Serial(PORT, BAUD, timeout=0.5)
    time.sleep(0.3)

    def send(cmd, wait=0.5):
        s.reset_input_buffer()
        s.write((cmd + "\r\n").encode("ascii"))
        time.sleep(wait)
        return s.read(900).decode("ascii", "replace").strip()

    def servo_us():
        txt = send("STATUS", 0.3)
        a = re.search(r"SERVO_ACTIVE=(\d+)", txt)
        u = re.search(r"SERVO_US=(\d+)", txt)
        return (a.group(1) if a else "?", u.group(1) if u else "?")

    print("=== 说明 ===")
    print("固件现行语义（ec_axis_driver.h:59-74）：")
    print("  P1100 = 张开 + 抬起（Z_UP，落料点用）")
    print("  P1900 = 闭合 + 下压（Z_DOWN，取料点用）")
    print("  中间档用于看行程是否线性、有无死区")
    print("每档停 %.0f 秒，请看夹爪/升降的实际动作。" % DWELL_S)
    print("PING ->", send("PING"))
    try:
        for i, us in enumerate(sweep, 1):
            print("\n########## [%d/%d] P%d us ##########" % (i, len(sweep), us))
            print("SERVO ARM      ->", send("SERVO ARM", 0.5))
            print("SERVO PB10 P%d ->" % us, send("SERVO PB10 P%d" % us, 0.4))
            print("  SERVO_ACTIVE/SERVO_US ->", servo_us())
            if i < len(sweep):
                print("  ……停 %.0f 秒观察" % DWELL_S)
                time.sleep(DWELL_S)
        print("\n########## 收尾：停脉宽 ##########")
        print("SERVO STOP ->", send("SERVO STOP", 0.5))
    finally:
        s.close()

    print("\n【请逐档记录】夹爪是张开还是闭合？升降是抬起还是下压？行程到没到位？有无死区/抖动？")
    print("记录格式建议：P1000=____  P1100=____  P1200=____  P1300=____")
    print("              P1500=____  P1700=____  P1900=____")
    return 0


if __name__ == "__main__":
    sys.exit(main())
