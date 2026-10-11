#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板子应答预检：反复 PING 直到拿到 PONG，或超时退出。

为什么要它：
  烧录/复位后板子有一段无应答期（实测约 20 秒仍未起）。若此时启动链路，
  主机发出去的 ITEM_TASK 全部石沉大海，日志只会刷「ITEM_TASK 超时 5.0s 无应答，
  重传」，看着像"板子坏了"，实际只是启动太早。
  历史上这个坑已经踩了两次（P900/P950 冷连接、18:53 整链）。

退出码：0=已应答  2=run_chain 在跑（拒绝占用串口）  3=超时未应答  4=串口打不开
"""

import subprocess
import sys
import time

PORT = "/dev/serial0"
BAUD = 115200


def main():
    timeout_s = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0

    if subprocess.run(["pgrep", "-f", "run_chain"], capture_output=True).stdout.strip():
        print("ABORT: run_chain 正在运行 —— 拒绝占用 %s" % PORT)
        return 2

    import serial
    try:
        s = serial.Serial(PORT, BAUD, timeout=0.5)
    except Exception as exc:                       # noqa: BLE001
        print("ABORT: 打不开 %s: %r" % (PORT, exc))
        return 4

    t0 = time.time()
    n = 0
    try:
        while time.time() - t0 < timeout_s:
            n += 1
            s.reset_input_buffer()
            s.write(b"PING\r\n")
            time.sleep(0.5)
            txt = s.read(400).decode("ascii", "replace")
            if "PONG" in txt:
                print("板子已应答 ✅  第 %d 次尝试，用时 %.1f 秒" % (n, time.time() - t0))
                return 0
            print("  第 %d 次无应答（%.1fs）……继续等" % (n, time.time() - t0))
            time.sleep(1.5)
    finally:
        s.close()

    print("❌ 板子 %.0f 秒内始终未应答 —— 拒绝启动链路。"
          "请确认：① 已按复位键 ② 供电正常 ③ 串口没被别人占用" % timeout_s)
    return 3


if __name__ == "__main__":
    sys.exit(main())
