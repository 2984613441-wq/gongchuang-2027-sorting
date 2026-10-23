#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从原点出发的【净空方框】丢步测试。

背景：2026-10-23 第一次方框测试起点 Y 恰在内壁上，第 4 腿把 Y 推回墙壁，
      若前面丢步就会堵转，但 STEP_RESULT 照样报 1 ⇒ 结论不可靠。
本脚本改进：先从原点走到净空中央（X+50mm、Y+50mm），再跑 50mm 方框，
      四条腿全部不碰墙，此时"是否回到起点"才是纯粹的丢步判据。

坐标规划（从 HOME 起，单位 mm）：
    起点       (0,   0   )   ← 物理原点
    定位后     (50,  50  )   ← 净空中央
    腿1 X+ →   (100, 50  )
    腿2 Y+ →   (100, 100 )
    腿3 X- →   (50,  100 )
    腿4 Y- →   (50,  50  )   ← 应回到定位点
上限 185/190mm，全程有余量。

方向（ec_motion_plan.h:61-62，2026-10-18 复测口径）：
    X+ = DIR0    Y+ = DIR0
"""
import re
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200
SPM = 80


def main():
    side_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 50.0
    steps = int(round(side_mm * SPM))

    s = serial.Serial(PORT, BAUD, timeout=0.1)
    time.sleep(0.3)

    def send(cmd, wait=0.15):
        s.reset_input_buffer()
        s.write((cmd + "\r\n").encode("ascii"))
        time.sleep(wait)
        return s.read(2000).decode("ascii", "replace").strip()

    def parse_status(txt):
        d = {}
        for line in txt.splitlines():
            line = line.strip()
            if line.startswith("STATUS"):
                for tok in line.split():
                    if "=" in tok:
                        k, v = tok.split("=", 1)
                        d[k] = v
        return d

    def status():
        s.reset_input_buffer()
        s.write(b"STATUS\r\n")
        deadline = time.time() + 0.15
        buf = b""
        while time.time() < deadline:
            chunk = s.read(2048)
            if chunk:
                buf += chunk
                if b"APP_STATE" in buf:
                    break
        return parse_status(buf.decode("ascii", "replace"))

    def do_move(axis, d, n, label, settle=0.4):
        """发一条 MOVE 并等它真正跑完（先见到 REMAIN>0 才认 0）。"""
        ack = send("MOTION ARM", 0.25)
        if "OK MOTION ARMED" not in ack:
            print("  !! ARM 失败: %s" % ack[:80])
            return False
        cmd = "MOVE %s DIR%s STEPS %d HZ 500" % (axis, d, n)
        ack = send(cmd, 0.12)
        if "OK MOTION STARTING" not in ack:
            print("  !! %s 未受理: %s" % (cmd, ack[:80]))
            return False
        t0 = time.time()
        started = False
        res = -1
        while time.time() - t0 < 25.0:
            st = status()
            rem = int(st.get("STEP_REMAIN", "-1") or -1)
            res = int(st.get("STEP_RESULT", "-1") or -1)
            if rem > 0:
                started = True
            if started and rem == 0:
                break
            if not started and time.time() - t0 > 3.0:
                print("  !! 没看到运动开始（%s）" % label)
                return False
            time.sleep(0.05)
        dt = time.time() - t0
        print("  %-18s %-34s %5.2fs  RESULT=%d" % (label, cmd, dt, res))
        time.sleep(settle)
        return res == 1

    ok = True
    print("PING ->", send("PING"))
    print("\n=== 阶段 1：走到净空中央（离两侧内壁各 50mm）===")
    ok &= do_move("X", "0", steps, "定位 X+")
    ok &= do_move("Y", "0", steps, "定位 Y+")

    print("\n=== 阶段 2：方框 %.0fmm（四腿全在净空内）===" % side_mm)
    legs = [
        ("X", "0", "腿1 X+"),
        ("Y", "0", "腿2 Y+"),
        ("X", "1", "腿3 X-"),
        ("Y", "1", "腿4 Y-"),
    ]
    for axis, d, label in legs:
        ok &= do_move(axis, d, steps, label, settle=0.6)

    print("\n=== 收尾状态 ===")
    st = status()
    print("  STEP_AXIS=%s STEP_REMAIN=%s STEP_RESULT=%s"
          % (st.get("STEP_AXIS"), st.get("STEP_REMAIN"), st.get("STEP_RESULT")))
    print("  PING ->", send("PING"))
    s.close()

    if not ok:
        print("\n!! 有动作未正常完成 —— 本次结果作废")
        return 3
    print("\n【请看】① 四条边是否各 %.0fmm ② 四个角是否直角"
          " ③ **最后是否回到定位点（与方框起点重合）** ④ 有无异响" % side_mm)
    print("注意：机械臂最后应停在【离两条内壁各 50mm】的位置，不是原点。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
