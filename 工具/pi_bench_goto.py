#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台架：从【已知真值】走到【目标真值】。

为什么需要这个：2026-09-19 用户断电后用手把 XY 推到 HOME 内角，
板子的逻辑位置已失真，台架 MOVE 又是相对步数。
所以真值由调用方显式传入并逐次累计，脚本只负责换算步数与护栏。

80 步/mm。X+ = DIR0，Y+ = DIR1（2026-09-19 实测核对过方向）。

⚠️ 两条台架硬事实（2026-09-19 实测，别再踩）：
  1. `MOVE ... HZ f` 的 f 【不生效】：ec_board_stm32.c:191-200 把 cruise
     硬编码成 5000U，只有规划失败才回落到 f。实测峰值 ~4900Hz = 62.5mm/s。
     所以任何基于"设定 HZ"的耗时估计都是错的。
  2. 完成判据必须【先看到 STEP_REMAIN>0】。发完 MOVE 后用 send(wait=0.4)
     再 read(timeout=0.5) 去轮询，第一次看到状态时已在 t≈1.1s，
     而 4000 步的一动只要 ~1.0s —— 于是永远看不到 >0，判据失效。

用法： python3 pi_bench_goto.py <cur_x> <cur_y> <tgt_x> <tgt_y>
"""
import sys
import time

import serial

PORT = "/dev/serial0"
STEPS_PER_MM = 80.0
HZ = 2000               # 仅用于回落到常频分支时；正常路径一律 5000Hz

X_MIN, X_MAX = -95.0, 90.0
# 🔴 2026-09-19 用户实测修正：物块放在 y=+12.5 且确实落在托盘上 ⇒
#    托盘从 HOME(-97.5) 起算 160mm，应覆盖到 y=+62.5，而不是"只有负 Y"。
#    旧值 Y_MAX=-2.0 建立在"正 Y 全是落料区"的旧假设上，已被否证。
#    硬件可达范围是 [-97.5, +92.5]（ec_motion_plan.h:127 REACH_Y_MM10 925），
#    这里仍留保守余量，不放到可达边界。用户 2026-09-19 明确同意放宽。
Y_MIN, Y_MAX = -97.5, 15.0
MAX_DELTA = 220.0

cur_x, cur_y, tgt_x, tgt_y = (float(a) for a in sys.argv[1:5])

if not (X_MIN <= tgt_x <= X_MAX):
    sys.exit("拒绝：目标 x=%.1f 超出托盘 [%.1f, %.1f]" % (tgt_x, X_MIN, X_MAX))
if not (Y_MIN <= tgt_y <= Y_MAX):
    sys.exit("拒绝：目标 y=%.1f 超出托盘 [%.1f, %.1f]" % (tgt_y, Y_MIN, Y_MAX))

s = serial.Serial(PORT, 115200, timeout=0.1)
time.sleep(0.3)


def handshake(cmd, tries=6):
    """握手命令要重试。

    2026-09-19 实测：打开串口后的【第一条命令经常丢】（只发一次的脚本反复
    第一次就收到 0 字节并 IndexError，而被误判成"板子失联"；
    而工具/pi_serial_wake.py 因为重试 10 次，每次都能拿到 OK PONG）。
    只对 PING / MOTION ARM 这类幂等握手用；MOVE 绝不能重试。
    """
    for _ in range(tries):
        txt = send(cmd)
        if txt:
            return txt
        time.sleep(0.15)
    return ""


def send(cmd, wait=0.15):
    # 🔴 握手必须用【长超时】：2026-09-19 为修轮询问题把 timeout 降到 0.1s，
    #    结果板子稍忙（发心跳）就收不到应答，直接 IndexError。轮询用短超时，
    #    握手用长超时，两者必须分开。
    s.timeout = 0.5
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(2000).decode("ascii", "replace").strip()


def status_fields():
    """快读：等到 APP_STATE 出现就返回，不做多余等待。"""
    s.timeout = 0.1
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
    for ln in buf.decode("ascii", "replace").splitlines():
        if "STEP_TARGET" in ln:
            d = {}
            for tok in ln.split():
                if "=" in tok:
                    k, _, v = tok.partition("=")
                    d[k] = v
            return d
    return {}


def as_int(d, key):
    v = d.get(key, "")
    return int(v) if v.isdigit() else -1


def jog(axis, delta_mm, plus_dir):
    steps = int(round(abs(delta_mm) * STEPS_PER_MM))
    if steps == 0:
        print("  %s 无需移动" % axis)
        return True
    direction = plus_dir if delta_mm > 0 else ("DIR1" if plus_dir == "DIR0" else "DIR0")
    cmd = "MOVE %s %s STEPS %d HZ %d" % (axis, direction, steps, HZ)
    print("  %s (=%+.1f mm)" % (cmd, delta_mm))

    arm = handshake("MOTION ARM")
    if "OK" not in arm:
        # 🔴 2026-09-19 修：arm 为空串时 splitlines()[0] 会 IndexError，
        #    本该报"ARM 失败"却变成脚本崩溃，把板子无响应掩盖成我的 bug。
        first = arm.splitlines()[0] if arm.strip() else "(空应答 —— 板子可能无响应)"
        print("    !! ARM 失败：%s  —— 该轴未移动" % first)
        return False

    reply = send(cmd, 0.12)          # 只等 0.12s，别把运动窗口等掉
    ok_line = [l.strip() for l in reply.splitlines() if "OK" in l or "ERR" in l]
    print("    应答:", ok_line[0] if ok_line else "(无 OK/ERR 行)")

    t0 = time.time()
    started = False
    res = -1
    while time.time() - t0 < 25.0:
        d = status_fields()
        rem = as_int(d, "STEP_REMAIN")
        if rem > 0:
            started = True
        if started and rem == 0:
            res = as_int(d, "STEP_RESULT")
            break
        if not started and time.time() - t0 > 4.0:
            break
    dt = time.time() - t0
    if not started:
        print("    !! 4 秒内没看到 STEP_REMAIN>0。板子答了 %s，"
              "但判据没抓到运动 —— 不可据此断定该轴没动" % (ok_line[0] if ok_line else "?"))
        return False
    print("    运动 %0.2fs  实测约 %.0f 步/秒  STEP_RESULT=%d (1=成功)"
          % (dt, steps / max(dt, 1e-6), res))
    return res == 1


dx, dy = tgt_x - cur_x, tgt_y - cur_y
if abs(dx) > MAX_DELTA or abs(dy) > MAX_DELTA:
    sys.exit("拒绝：单轴位移过大 dx=%.1f dy=%.1f（上限 %.0f mm）" % (dx, dy, MAX_DELTA))

_pong = handshake("PING")
print("PING ->", (_pong.splitlines()[0] if _pong else "!! 6 次重试都没应答"))
print("从真值 (%.1f, %.1f) 走到 (%.1f, %.1f)：Δ=(%+.1f, %+.1f) mm" %
      (cur_x, cur_y, tgt_x, tgt_y, dx, dy))
ok_x = jog("X", dx, "DIR0")
ok_y = jog("Y", dy, "DIR1")

if ok_x and ok_y:
    print("\n=> 新的真值 = (%.1f, %.1f) mm" % (tgt_x, tgt_y))
else:
    print("\n!! 判据没抓全 —— 板子答了 OK 就很可能真的动了，"
          "请用 pi_state_now.py / pi_step_trace.py 复核后再决定真值")
    sys.exit(1)
s.close()
