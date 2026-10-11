#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针：向 STM32 诊断口发 PING / INPUTS / STATUS，打印原始应答并解码安全位。

用途（2026-09-18 定案实验）：
  ec_state_machine.c:44 —— ec_sm_init() 把状态机初始化为 EC_STATE_FAULT_LOCK。
  离开 FAULT_LOCK 只有两条路（:95-115），其中 ITEM_TASK 那条带安全前置：
      danger_area_clear && estop_released
  而这两个量在 ec_app.c:619-622 由 active_mask 算出：
      danger_area_clear = (ACTIVE & ESTOP_FB)==0 && (ACTIVE & MANUAL_RESET)==0
      estop_released    = (ACTIVE & ESTOP_FB)==0
  ACTIVE 位=1 ⟺ 引脚为 LOW（ec_board_stm32.c:85-90 宏读 HIGH 置 raw，active 取反）。

  所以若 ACTIVE 的 bit6(0x0040) 或 bit8(0x0100) 为 1，板子【永远】进不了 POWER_ON：
  ITEM_TASK 会被 ACK，但轮次建立不起来 → 不动、不发 MOTION_DONE，且与运动/超时/掉电无关。

只读保证：
  · 只发 PING / INPUTS / STATUS 三个无副作用命令，不发任何 ARM / MOVE / STEP。
  · 绝不与 run_chain.py 同时占用 /dev/serial0 —— 检测到在跑就直接退出。
"""

import re
import subprocess
import sys
import time

PORT = "/dev/serial0"
BAUD = 115200

ESTOP_FB = 6      # ec_inputs.h:12   0x0040
START_SIG = 7     # ec_inputs.h:13   0x0080
MANUAL_RESET = 8  # ec_inputs.h:14   0x0100
LOCK_MASK = (1 << ESTOP_FB) | (1 << MANUAL_RESET)  # 0x0140


def chain_running():
    out = subprocess.run(["pgrep", "-f", "run_chain"],
                         capture_output=True).stdout.strip()
    return bool(out)


def main():
    if chain_running():
        print("ABORT: run_chain IS RUNNING — refusing to touch %s" % PORT)
        return 2

    try:
        import serial
    except ImportError:
        print("ABORT: pyserial not available")
        return 3

    try:
        s = serial.Serial(PORT, BAUD, timeout=0.5)
    except Exception as exc:                       # noqa: BLE001
        print("ABORT: cannot open %s: %r" % (PORT, exc))
        return 3

    time.sleep(0.3)
    verdict = None
    try:
        for cmd in ("PING", "INPUTS", "STATUS", "INPUTS", "STATUS"):
            s.reset_input_buffer()
            s.write((cmd + "\r\n").encode("ascii"))
            time.sleep(0.6)
            txt = s.read(900).decode("ascii", "replace").strip()
            print("=== %s -> %s" % (cmd, txt if txt else "(NO REPLY)"))

            m = re.search(r"ACTIVE=([0-9A-Fa-f]{4})", txt)
            if m:
                v = int(m.group(1), 16)
                print("    ACTIVE=%04X  ESTOP_FB(bit6)=%d  START(bit7)=%d  "
                      "MANUAL_RESET(bit8)=%d"
                      % (v, (v >> ESTOP_FB) & 1, (v >> START_SIG) & 1,
                         (v >> MANUAL_RESET) & 1))
                locked = bool(v & LOCK_MASK)
                print("    LOCKED_OUT(bit6|bit8) = %s" % locked)
                verdict = locked
            m2 = re.search(r"APP_STATE=(\S+)", txt)
            if m2:
                print("    APP_STATE = %s" % m2.group(1))
    finally:
        s.close()

    print("-" * 60)
    if verdict is None:
        print("判定：【无效】INPUTS 无应答 —— 端口/供电/波特率或固件版本需排查")
        return 4
    if verdict:
        print("判定：🔴 安全输入未释放 → 板子被设计锁在 FAULT_LOCK。")
        print("      根因在安全输入接线/极性，不在运动层。")
    else:
        print("判定：🟢 安全条件成立 → 板子会进 POWER_ON/POST。")
        print("      故障在启动序列或运动层，此时才需要烧 AXIS 版固件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
