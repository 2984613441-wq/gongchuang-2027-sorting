#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""滑台「单一落料点」测量工具（台架步进 X/Y，STM32 相对步数）。

为什么需要单独一个：
  现有 工具/pi_bench_goto.py 的 Y 上限被**保守限制在 +15mm**（当时按托盘范围收紧），
  而 360° 转盘的固定落点很可能在 Y 正方向远端（模板里是 88/90）。
  本脚本把范围放到**硬件可达域**，但要求显式 `--yes` 才动，且单次位移 ≤ 20mm。

━━━ 两条台架硬事实（2026-09-19 实测，别踩）━━━━━━━━━━━━━━━━━━━
  1. 80 步/mm；X+ = DIR0、Y+ = DIR1。
  2. `MOVE ... HZ f` 里的 f **不生效**（固件把 cruise 硬编码 5000Hz）；
     完成判据必须"先看到 STEP_REMAIN>0 再看到 0"。

━━━ 用法（注意：坐标用独立参数，避免负数被当成选项）━━━━━━━━━━━━━
  # 只看计划（不动）
  python3 measure_drop_point.py --cur-x -40 --cur-y 80 --tgt-x -38 --tgt-y 82
  # 真的走 2mm
  python3 measure_drop_point.py --cur-x -40 --cur-y 80 --tgt-x -38 --tgt-y 82 --yes
  # 单轴点动
  python3 measure_drop_point.py --cur-x -40 --cur-y 80 --jog-axis X --jog-delta 2 --yes

━━━ 安全红线 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · X/Y **无限位开关**，超程会堵转并把主控带挂（实测已发生 3 次）
  · 本脚本绝不发 HOME / RESET / STOP ALL；每次移动 ≤ 20mm
  · Y 超过 +15mm 需要额外 `--allow-far-y`（确认托盘/转盘已就位、无遮挡）
"""

from __future__ import annotations

import argparse
import sys
import time

STEPS_PER_MM = 80.0
HZ = 5000
PORT = "/dev/serial0"
BAUD = 115200

X_MIN, X_MAX = -95.0, 90.0
Y_MIN, Y_MAX = -97.5, 92.5
MAX_DELTA_MM = 20.0
FAR_Y = 15.0


def handshake(s, cmd, tries=6):
    for _ in range(tries):
        txt = send(s, cmd)
        if txt:
            return txt
        time.sleep(0.15)
    return ""


def send(s, cmd, wait=0.15):
    s.timeout = 0.5
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(2000).decode("ascii", "replace").strip()


def status_fields(s):
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


def jog(s, axis, delta_mm, plus_dir):
    steps = int(round(abs(delta_mm) * STEPS_PER_MM))
    if steps == 0:
        print("  %s 无需移动" % axis)
        return True
    direction = plus_dir if delta_mm > 0 else ("DIR1" if plus_dir == "DIR0" else "DIR0")
    cmd = "MOVE %s %s STEPS %d HZ %d" % (axis, direction, steps, HZ)
    print("  %s (=%+.1f mm)" % (cmd, delta_mm))

    arm = handshake(s, "MOTION ARM")
    if "OK" not in arm:
        first = arm.splitlines()[0] if arm.strip() else "(空应答 —— 板子可能无响应)"
        print("    !! ARM 失败：%s —— 该轴未移动" % first)
        return False

    reply = send(s, cmd, 0.12)
    ok_line = [l.strip() for l in reply.splitlines() if "OK" in l or "ERR" in l]
    print("    应答:", ok_line[0] if ok_line else "(无 OK/ERR 行)")

    t0 = time.time()
    started = False
    res = -1
    while time.time() - t0 < 25.0:
        d = status_fields(s)
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
        print("    !! 4 秒内没看到 STEP_REMAIN>0 —— 不可据此断定该轴没动")
        return False
    print("    运动 %.2fs  STEP_RESULT=%d (1=成功)" % (dt, res))
    return res == 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="滑台单一落点测量（X/Y 相对步数）")
    ap.add_argument("--cur-x", type=float, required=True, help="当前【已知真值】X（mm）")
    ap.add_argument("--cur-y", type=float, required=True, help="当前【已知真值】Y（mm）")
    ap.add_argument("--tgt-x", type=float, help="目标真值 X（mm）")
    ap.add_argument("--tgt-y", type=float, help="目标真值 Y（mm）")
    ap.add_argument("--jog-axis", choices=("X", "Y"), help="单轴点动：轴名")
    ap.add_argument("--jog-delta", type=float, help="单轴点动：位移 mm（可负）")
    ap.add_argument("--yes", action="store_true", help="真的移动（不加只打印计划）")
    ap.add_argument("--allow-far-y", action="store_true", help="允许 Y>+15mm（确认无遮挡）")
    ap.add_argument("--dry-run", action="store_true", help="完全不连串口")
    args = ap.parse_args(argv)

    cur_x, cur_y = float(args.cur_x), float(args.cur_y)
    moves: list[tuple[str, float]] = []
    if args.jog_axis:
        if args.jog_delta is None:
            raise SystemExit("--jog-axis 需要同时给 --jog-delta")
        axis, delta = args.jog_axis, float(args.jog_delta)
        moves.append((axis, delta))
        tgt_x = cur_x + (delta if axis == "X" else 0.0)
        tgt_y = cur_y + (delta if axis == "Y" else 0.0)
    elif args.tgt_x is not None and args.tgt_y is not None:
        tgt_x, tgt_y = float(args.tgt_x), float(args.tgt_y)
        moves = [("X", tgt_x - cur_x), ("Y", tgt_y - cur_y)]
    else:
        raise SystemExit("需要 --tgt-x/--tgt-y 或 --jog-axis/--jog-delta")

    # ---- 护栏 ----
    if not (X_MIN <= tgt_x <= X_MAX):
        raise SystemExit("拒绝：目标 x=%.1f 超出可达域 [%.1f, %.1f]" % (tgt_x, X_MIN, X_MAX))
    if not (Y_MIN <= tgt_y <= Y_MAX):
        raise SystemExit("拒绝：目标 y=%.1f 超出可达域 [%.1f, %.1f]" % (tgt_y, Y_MIN, Y_MAX))
    for axis, delta in moves:
        if abs(delta) > MAX_DELTA_MM:
            raise SystemExit("拒绝：单轴位移 %.1fmm 超过 %.0fmm 上限（分多次走）"
                             % (delta, MAX_DELTA_MM))
    if (tgt_y > FAR_Y or cur_y > FAR_Y) and not args.allow_far_y:
        raise SystemExit("拒绝：Y=%.1fmm 超过保守线 +%.0fmm。确认托盘/转盘就位且无遮挡后，"
                         "再加 --allow-far-y" % (max(tgt_y, cur_y), FAR_Y))

    print("从真值 (%.1f, %.1f) 走到 (%.1f, %.1f)：Δ=(%+.1f, %+.1f) mm"
          % (cur_x, cur_y, tgt_x, tgt_y, tgt_x - cur_x, tgt_y - cur_y))
    for axis, delta in moves:
        print("  计划 MOVE %s %s STEPS %d" % (
            axis, "+" if delta > 0 else "-", int(round(abs(delta) * STEPS_PER_MM))))

    if args.dry_run or not args.yes:
        print("\n[dry-run / 未加 --yes] 未执行任何动作。确认无误后加 --yes 重跑。")
        return 0

    import serial  # 延迟导入

    s = serial.Serial(PORT, BAUD, timeout=0.1)
    time.sleep(0.3)
    try:
        pong = handshake(s, "PING")
        print("PING ->", (pong.splitlines()[0] if pong else "!! 6 次重试都没应答"))
        if not pong:
            return 2
        st = send(s, "STATUS", 0.2)
        for ln in st.splitlines():
            if "APP_STATE" in ln:
                print("STATUS:", ln.strip()[:160])
                break
        ok_all = True
        for axis, delta in moves:
            plus = "DIR0" if axis == "X" else "DIR1"
            if not jog(s, axis, delta, plus):
                ok_all = False
                print("!! %s 轴未确认成功，停止后续移动（真值不要继续累加）" % axis)
                break
        if ok_all:
            print("\n移动完成。记下当前真值 = (%.1f, %.1f) mm" % (tgt_x, tgt_y))
            print("若此时落料口正对目标格中心 ⇒ 这就是 turntable_drop_point 的滑台记账坐标")
        return 0 if ok_all else 3
    finally:
        s.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
