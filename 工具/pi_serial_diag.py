#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""串口链路诊断：树莓派 → STM32 到底通不通（只读观察 + 一条 PING）。

判据很简单：
  · 先【只听不发】8 秒。固件的 App 层会 1Hz 主动发 `STATUS ...` 心跳。
      听得到心跳 → 链路是通的，问题在协议/App 层；
      一点字节都没有 → 接线或供电的问题（或者板子在 diag 待机、或压根没跑 App）。
  · 再发一条 `PING`，看有没有应答。

用法：python3 pi_serial_diag.py
"""

import glob
import os
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200


def main() -> int:
    print("=" * 62)
    print("串口链路诊断  port=%s  baud=%d" % (PORT, BAUD))
    print("=" * 62)

    # 0) 设备本身在不在
    real = os.path.realpath(PORT)
    print("设备      : %s -> %s  %s" % (PORT, real, "存在" if os.path.exists(real) else "**不存在**"))
    for pat in ("/dev/ttyAMA*", "/dev/ttyS*", "/dev/ttyUSB*"):
        found = sorted(glob.glob(pat))
        if found:
            print("  同族设备: %s" % " ".join(found))
    if not os.path.exists(real):
        print("→ 串口设备不存在，先把 /dev/serial0 弄出来（config.txt 的 enable_uart=1）")
        return 2

    # 1) 只听不发
    try:
        port = serial.Serial(PORT, BAUD, timeout=0.3)
    except Exception as exc:
        print("打不开串口: %r" % (exc,))
        print("→ 是不是链路进程还占着？先 pkill -f 'deploy/run_chain.py'")
        return 3

    print("\n[1] 只听不发 8 秒（等固件的 1Hz STATUS 心跳）...")
    port.reset_input_buffer()
    buf = bytearray()
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        chunk = port.read(4096)
        if chunk:
            buf += chunk
    print("    收到 %d 字节" % len(buf))
    if buf:
        text = buf.decode("utf-8", "replace")
        print("    原文（前 600 字）:")
        for line in text.splitlines()[:20]:
            print("      | %s" % line)
        print("→ ✅ 链路是通的：STM32 在主动说话。问题不在接线，在协议/App 层。")
    else:
        print("→ ❌ 一个字节都没有。三种可能：")
        print("     a) 接线：TX/RX 接反或没接（PA2=TX 要接树莓派 RXD/GPIO15）")
        print("     b) 共地：两边 GND 必须连在一起")
        print("     c) 板子没跑 App（没上电 / 停在别的地方 / 没烧固件）")

    # 2) 发 PING
    print("\n[2] 发一条 PING ...")
    port.reset_input_buffer()
    port.write(b"PING\r\n")
    port.flush()
    time.sleep(1.0)
    reply = port.read(4096)
    print("    回应 %d 字节: %r" % (len(reply), bytes(reply[:200])))
    if reply:
        print("→ ✅ 有应答，双向通了。")
    else:
        print("→ ❌ 无应答（与上一步结论一致）。")

    port.close()
    print("\n" + "=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
