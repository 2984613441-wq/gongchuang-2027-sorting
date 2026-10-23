#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STM32 台架命令行工具（可传多条命令）。

用法：
  python3 stm32_cmd.py "PING" "STATUS" "AXIS"
  python3 stm32_cmd.py "MOVE X DIR0 STEPS 7200 HZ 2000"

与 pi_light.py 的区别：
  * 不过滤 STATUS（需要看状态时不能丢）
  * 支持一次性多条命令
  * 每条命令的回显单独打印

注意：本工具不做任何安全判断，调用方负责确认机械臂位置。
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200


def drain(ser, seconds):
    buf = b""
    end = time.time() + seconds
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.02)
    return buf.decode("ascii", "replace")


def main():
    cmds = sys.argv[1:]
    if not cmds:
        print("用法: python3 stm32_cmd.py <命令1> [命令2 ...]")
        return 2

    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    time.sleep(0.4)
    boot = drain(ser, 0.8)
    if boot.strip():
        print("[开机残留] %s" % boot.strip()[-300:])
        print()

    rc = 0
    for cmd in cmds:
        print(">>> %s" % cmd)
        ser.write((cmd + "\r\n").encode("ascii"))
        ser.flush()
        time.sleep(0.35)
        out = drain(ser, 1.2)
        got = False
        for line in out.splitlines():
            line = line.strip()
            if line:
                print("    %s" % line)
                got = True
        if not got:
            print("    (无应答)")
            rc = 1
        print()
    ser.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
