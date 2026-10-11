# -*- coding: utf-8 -*-
"""一次性读板子 STATUS / AXIS（只读，不发任何运动或伺服命令）。

用途：确认「被中断的 SERVO 测试有没有留下动作」，以及板子当前状态。
写它的原因：本地 PowerShell 里用 `python -c "..."` 嵌引号会被啃烂，
不如落一个文件 scp 过去 —— 一次解决，以后都能用。
"""
import serial
import sys
import time

PORT = "/dev/serial0"


def main():
    s = serial.Serial(PORT, 115200, timeout=0.4)
    time.sleep(0.3)

    def send(cmd, wait=0.35):
        s.reset_input_buffer()
        s.write((cmd + "\r\n").encode("ascii"))
        time.sleep(wait)
        return s.read(6000).decode("ascii", "replace").strip()

    print("PING -> " + (send("PING").splitlines() or ["(空)"])[0].strip())
    for cmd in ("STATUS", "AXIS"):
        print("---- %s ----" % cmd)
        for line in send(cmd).splitlines():
            line = line.strip()
            if line:
                print("   " + line)
    s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
