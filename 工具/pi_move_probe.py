#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运动探针：把每一次收发都原样打印，不再做任何过滤或"智能解析"。

教训（2026-09-18）：上一版脚本自己制造了两个假象 ——
  1) 读状态前 flush 输入缓冲，把一条正在传输的 350 字节 STATUS 截成半条，
     残留字节被当成本次命令的应答，于是读到 REMAIN=0 误判成"瞬间走完"；
  2) 后来干脆不打印 MOVE 的应答，于是"命令被拒绝"和"运动没跑"分不清。
本脚本只做一件事：说什么、回什么，全部照抄。

用法： python3 -u pi_move_probe.py <axis> <dir> <steps> <hz>
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200


def talk(ser, cmd, wait):
    """发一条命令，读 wait 秒，把收到的东西原样返回。"""
    ser.reset_input_buffer()
    time.sleep(0.06)
    ser.write((cmd + "\r\n").encode("ascii"))
    ser.flush()
    end = time.time() + wait
    out = bytearray()
    while time.time() < end:
        n = ser.in_waiting
        if n:
            out += ser.read(n)
        else:
            time.sleep(0.01)
    return bytes(out).decode("ascii", "replace")


def main():
    axis = sys.argv[1] if len(sys.argv) > 1 else "Y"
    direction = sys.argv[2] if len(sys.argv) > 2 else "1"
    steps = sys.argv[3] if len(sys.argv) > 3 else "800"
    hz = sys.argv[4] if len(sys.argv) > 4 else "200"

    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    try:
        for cmd, wait in (("INPUTS", 1.5), ("MOTION ARM", 1.5)):
            print(">>> %s" % cmd)
            print(talk(ser, cmd, wait).rstrip())
            print("")

        cmd = "MOVE %s DIR%s STEPS %s HZ %s" % (axis, direction, steps, hz)
        print(">>> %s   (= %.1f mm, 理论 %.1f 秒)"
              % (cmd, int(steps) / 80.0, int(steps) / float(hz)))
        ser.reset_input_buffer()
        ser.write((cmd + "\r\n").encode("ascii"))
        ser.flush()

        # 被动观察 8 秒：只读板子自己发的 1Hz STATUS。
        # 不再主动发 STATUS —— 那样必须先 flush，会截断正在传输的一条心跳。
        print("--- 被动观察 8 秒（只读 1Hz 心跳）---")
        t0 = time.time()
        buf = ""
        while time.time() - t0 < 8.0:
            n = ser.in_waiting
            if not n:
                time.sleep(0.02)
                continue
            buf += ser.read(n).decode("ascii", "replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip("\r")
                if line:
                    print("  [%5.2fs] %s" % (time.time() - t0,
                                             line if len(line) < 200
                                             else line[:200] + " ..."))

        print("")
        print(">>> STOP ALL")
        print(talk(ser, "STOP ALL", 1.0).rstrip())
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
