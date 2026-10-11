#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AXIS 仪器读数：连续轮询 STM32 的 AXIS 命令，用 TICK_MS 是否跳水判定复位。

为什么这样能判定复位：
  · TICK_MS = HAL_GetTick()，**复位后归零** → 若 TICK_MS 由大跳到小，就是复位。
  · FAULTS 是 ec_axis_driver.c 的 .bss 静态量；启动代码清零，但
    ec_axis_driver_init() 故意不清（见 latch_fault_diag），所以
      FAULTS>0  ⇒ 发生过软件故障且此后没复位过
      FAULTS=0  ⇒ 要么没故障，要么故障后被复位清掉了

只用 PING/AXIS 两个无副作用命令，不发 ARM/MOVE/STEP。检测到 run_chain 在跑会拒绝执行。
"""

import re
import subprocess
import sys
import time

PORT = "/dev/serial0"
BAUD = 115200

RESULT_NAME = {
    0: "OK", 1: "BUSY", 2: "INVALID_PARAM", 3: "INHIBITED",
    4: "TIMEOUT", 5: "ABORTED", 6: "PORT_FAIL",
}
KIND_NAME = {0: "MOVE", 1: "GRIPPER", 2: "Z_SERVO", 3: "MOVE_XY", 4: "XY_INTERP"}
STATE_NAME = {0: "IDLE", 1: "MOVING", 2: "GRIPPING", 3: "DONE", 4: "FAULT"}


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    if subprocess.run(["pgrep", "-f", "run_chain"], capture_output=True).stdout.strip():
        print("ABORT: run_chain 正在运行 —— 拒绝占用 /dev/serial0")
        return 2
    import serial
    s = serial.Serial(PORT, BAUD, timeout=1.0)
    time.sleep(0.3)

    print("时间      TICK_MS   FAULTS STATE      RESULT     PROGRESS MOVES "
          "LAST_RESULT   LAST_STEP/LEN LAST_KIND  LAST_ELAPSED/TIMEOUT")
    print("-" * 130)
    prev_tick = None
    resets = 0
    t0 = time.time()
    try:
        while time.time() - t0 < secs:
            s.reset_input_buffer()
            s.write(b"AXIS\r\n")
            time.sleep(0.5)
            txt = s.read(1200).decode("ascii", "replace")
            m = re.search(r"AXIS (FAULTS=\d+.*?)\r?\n", txt)
            if not m:
                print("%s  (NO AXIS REPLY —— 固件可能还没烧 AXIS 版)"
                      % time.strftime("%H:%M:%S"))
                time.sleep(1.5)
                continue
            kv = dict(re.findall(r"([A-Z_]+)=(\d+)", m.group(1)))
            tick = int(kv.get("TICK_MS", -1))
            flag = ""
            if prev_tick is not None and tick < prev_tick:
                resets += 1
                flag = "  <<< TICK_MS 跳水 → 复位 #%d" % resets
            prev_tick = tick
            print("%s  %7d  %6s %-10s %-10s %8s %5s %-13s %5s/%-5s %-10s %8s/%-8s%s" % (
                time.strftime("%H:%M:%S"),
                tick,
                kv.get("FAULTS", "?"),
                "%s(%s)" % (kv.get("STATE", "?"), STATE_NAME.get(int(kv.get("STATE", -1)), "?")),
                "%s(%s)" % (kv.get("RESULT", "?"), RESULT_NAME.get(int(kv.get("RESULT", -1)), "?")),
                kv.get("PROGRESS", "?"), kv.get("MOVES", "?"),
                "%s(%s)" % (kv.get("LAST_RESULT", "?"),
                            RESULT_NAME.get(int(kv.get("LAST_RESULT", -1)), "?")),
                kv.get("LAST_STEP", "?"), kv.get("LAST_LEN", "?"),
                "%s(%s)" % (kv.get("LAST_KIND", "?"),
                            KIND_NAME.get(int(kv.get("LAST_KIND", -1)), "?")),
                kv.get("LAST_ELAPSED_MS", "?"), kv.get("LAST_TIMEOUT_MS", "?"),
                flag))
            time.sleep(1.0)
    finally:
        s.close()

    print("-" * 130)
    print("观察 %.0f 秒，检测到 TICK_MS 跳水（复位）次数 = %d" % (secs, resets))
    if resets:
        print("判定：🔴 板子在复位 → 往供电/复位源查")
    else:
        print("判定：🟢 TICK_MS 单调，板子没复位 → 看 FAULTS / LAST_RESULT 定软件故障")
    return 0


if __name__ == "__main__":
    sys.exit(main())
