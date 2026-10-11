#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Y 轴方向自检：小幅移动，人工确认 device +Y 到底对应 DIR1 还是 DIR0。

为什么必须先做这一步：标定表假设 device +Y = DIR1（a22 = +1.083333），
但这条映射从未在实机上验证。若符号相反，链路命令轴去 Y=-90（托盘中部）时，
轴会朝反方向一路跑到机械限位 -> 堵转 + 挂死（已经发生过两次）。
本脚本只走 STEPS 步（默认 400 步 = 5mm），离两端都远，撞不到限位。

用法： python3 -u pi_dir_check.py [axis] [dir] [steps] [hz]
       python3 -u pi_dir_check.py Y 1 400 400
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200


def xfer(ser, cmd, wait=1.2):
    """发一条 ASCII 命令，收 wait 秒的回复。"""
    ser.reset_input_buffer()
    time.sleep(0.05)
    ser.write((cmd + "\r\n").encode("ascii"))
    ser.flush()
    end = time.time() + wait
    buf = bytearray()
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.01)
    return bytes(buf).decode("ascii", "replace")


def field(text, key):
    """取【最后一条】STATUS —— 缓冲里可能同时有 1Hz 心跳和本条命令的应答，
    取第一条会读到旧状态（这是先前 DIR1 异常读数的可能来源）。"""
    for line in reversed(text.splitlines()):
        if line.startswith("STATUS"):
            for tok in line.split():
                if tok.startswith(key + "="):
                    return tok.split("=", 1)[1]
    return None


def main():
    axis = sys.argv[1] if len(sys.argv) > 1 else "Y"
    direction = sys.argv[2] if len(sys.argv) > 2 else "1"
    steps = sys.argv[3] if len(sys.argv) > 3 else "400"
    hz = sys.argv[4] if len(sys.argv) > 4 else "400"

    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    try:
        print("== 1) INPUTS（确认急停/手动复位没被触发）==")
        print(xfer(ser, "INPUTS", 1.0).strip())

        print("")
        print("== 2) MOTION ARM（10 秒窗口；本命令本身不产生任何运动）==")
        r = xfer(ser, "MOTION ARM", 1.0)
        print(r.strip())
        if "OK MOTION ARMED" not in r:
            print("!! 没武装成功 —— 先别动，把上面输出发给我")
            return 1

        print("")
        print("== 3) 发送前状态 ==")
        before = xfer(ser, "STATUS", 1.2)
        print("    STEP_AXIS=%s STEP_TARGET=%s STEP_REMAIN=%s STEP_RESULT=%s"
              % (field(before, "STEP_AXIS"), field(before, "STEP_TARGET"),
                 field(before, "STEP_REMAIN"), field(before, "STEP_RESULT")))

        cmd = "MOVE %s DIR%s STEPS %s HZ %s" % (axis, direction, steps, hz)
        print("")
        print("== 4) 发命令: %s  (= %.1f mm)" % (cmd, int(steps) / 80.0))
        ser.reset_input_buffer()
        ser.write((cmd + "\r\n").encode("ascii"))
        ser.flush()

        # == 5) 被动观察 ==
        # 关键：发完命令后【不再主动发 STATUS】。主动发任何命令之前都得 flush 输入
        # 缓冲，而一条 STATUS 约 350 字节、在 115200 下要传约 30ms；若它正好传到一半，
        # flush 只清掉已缓冲的部分，剩下半条旧行随后到达，会被当成本次命令的应答 -
        # 表现为读到 REMAIN=0 而误判成"瞬间走完"。只读板子自己发的 1Hz 心跳没有这个洞。
        print("== 5) 被动观察 8 秒（只读 1Hz 心跳，不插话）==")
        t0 = time.time()
        buf = ""
        max_remain = 0
        while time.time() - t0 < 8.0:
            n = ser.in_waiting
            if not n:
                time.sleep(0.02)
                continue
            buf += ser.read(n).decode("ascii", "replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if not line.startswith("STATUS"):
                    continue
                tok = {}
                for kv in line.split():
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        tok[k] = v
                try:
                    rem = int(tok.get("STEP_REMAIN", "0"))
                except ValueError:
                    rem = 0
                max_remain = max(max_remain, rem)
                print("    t=%.1fs MODE=%s AXIS=%s TARGET=%s REMAIN=%s RESULT=%s"
                      % (time.time() - t0, tok.get("MODE"), tok.get("STEP_AXIS"),
                         tok.get("STEP_TARGET"), rem, tok.get("STEP_RESULT")))
        print("    >>> 本趟见到的 STEP_REMAIN 最大值 = %d" % max_remain)

        print("")
        print("== 6) STOP ALL ==")
        print(xfer(ser, "STOP ALL", 0.8).strip())
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
