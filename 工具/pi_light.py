#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台架命令小工具：发任意调试命令并回读（自动过滤 1Hz 无请求 STATUS 心跳）。

用法：
  python3 pi_light.py                      # 默认 PING + LIGHT ON
  python3 pi_light.py "LIGHT OFF"
  python3 pi_light.py HELP
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200


def drain(ser, seconds=0.4):
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.02)
    return buf.decode("ascii", "replace")


def main():
    cmds = sys.argv[1:] if len(sys.argv) > 1 else ["PING", "LIGHT ON"]
    ser = serial.Serial(PORT, BAUD, timeout=0.15)
    time.sleep(0.5)

    boot = drain(ser, 1.0)
    if boot.strip():
        print("[开机残留] %s" % boot.strip()[-200:])

    for cmd in cmds:
        print(">>> %s" % cmd)
        ser.write((cmd + "\r\n").encode("ascii"))
        ser.flush()
        time.sleep(0.4)
        out = drain(ser, 1.0)
        got = False
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("STATUS"):
                continue          # 无请求心跳，丢掉
            print("    %s" % line)
            got = True
        if not got:
            print("    (无应答)")
    ser.close()


if __name__ == "__main__":
    main()
