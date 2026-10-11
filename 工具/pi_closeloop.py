#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闭环一轮：听一帧 → 算物块的装置坐标 D → 把夹爪开到 D。

为什么这样设计：夹爪真值记账不可靠（回程差 + 历史歧义），
所以**不依赖记账**——从调用方给的已知起点出发，用相对步数走到 D，
然后靠用户目视报残差。残差就是总误差，直接拿去修 tx/ty，1~2 轮即收敛。

三个中心不要混淆（2026-09-19 用户明确）：
  摄像头中心 ≠ Z轴中心 ≠ 夹爪中心
  摄像头中心 相对 Z轴 在 X 正方向约 4cm；Z轴中心 与 夹爪中心 之间也还差 4cm。

用法： python3 pi_closeloop.py <cur_x> <cur_y> [监听秒数=8]
"""
import socket
import sys
import time

import serial

sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter   # noqa: E402
from electrical_control.rpi.vision_ingest import parse_batch_targets        # noqa: E402

CAL = "/home/pi/电控/calibration_config.ini"
PORT = "/dev/serial0"
STEPS_PER_MM = 80.0
HZ = 2000
X_MIN, X_MAX = -95.0, 90.0
Y_MIN, Y_MAX = -97.5, -2.0

cur_x, cur_y = float(sys.argv[1]), float(sys.argv[2])
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0

conv = PixelToDeviceConverter(CAL)


def raw_value(key):
    with open(CAL, encoding="utf-8") as fh:
        for ln in fh:
            body = ln.split("#", 1)[0].strip()
            if body.startswith(key + " ="):
                return float(body.split("=", 1)[1].strip())
    return float("nan")


print("现行标定: a11=%.6f a22=%.6f tx=%.3f ty=%.3f" %
      (raw_value("a11"), raw_value("a22"), raw_value("tx"), raw_value("ty")))

# ---------- 1. 听一帧 ----------
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 8765))
srv.listen(4)
srv.settimeout(1.0)

seen = {}
t_end = time.time() + seconds
while time.time() < t_end:
    try:
        conn, _ = srv.accept()
    except socket.timeout:
        continue
    conn.settimeout(2.0)

    def recv_n(n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                break
            buf += chunk
        return buf

    try:
        head = recv_n(3)
        if len(head) == 3:
            data = head + recv_n(head[0] * 7)
            if len(data) == 3 + head[0] * 7:
                for t in parse_batch_targets(data).targets:
                    n, _, _, _ = seen.get(t.box_id, (0, 0, 0, None))
                    seen[t.box_id] = (n + 1, t.pixel_x, t.pixel_y,
                                      conv.pixel_to_device(t.pixel_x, t.pixel_y, t.box_id))
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()
srv.close()

if not seen:
    sys.exit("一帧都没收到 —— 物块没被检出（出黄框了？被夹爪挡了？）")

print("\n=== 收到的目标 ===")
for bid, (n, px, py, got) in sorted(seen.items()):
    print("  box_id=%d  %d 帧  px=%d py=%d -> %s" % (bid, n, px, py, got))

# 取帧数最多的那个当主目标
bid, (n, px, py, got) = max(seen.items(), key=lambda kv: kv[1][0])
if got is None:
    sys.exit("\n主目标 box_id=%d 被拒识（越界），无法定位 —— 先把物块挪到托盘内部" % bid)

tgt_x, tgt_y = got[0] / 10.0, got[1] / 10.0
print("\n主目标 box_id=%d（%d 帧）px=%d py=%d -> D=(%.1f, %.1f) mm" %
      (bid, n, px, py, tgt_x, tgt_y))

# ---------- 2. 开过去 ----------
if not (X_MIN <= tgt_x <= X_MAX):
    sys.exit("拒绝：目标 x=%.1f 超出托盘 [%.1f, %.1f]" % (tgt_x, X_MIN, X_MAX))
if not (Y_MIN <= tgt_y <= Y_MAX):
    sys.exit("拒绝：目标 y=%.1f 超出托盘 [%.1f, %.1f]" % (tgt_y, Y_MIN, Y_MAX))

dx, dy = tgt_x - cur_x, tgt_y - cur_y
print("从真值 (%.1f, %.1f) 开过去：Δ=(%+.1f, %+.1f) mm" % (cur_x, cur_y, dx, dy))

s = serial.Serial(PORT, 115200, timeout=0.1)
time.sleep(0.3)


def send(cmd, wait=0.15):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(2000).decode("ascii", "replace").strip()


def status_fields():
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


def jog(axis, delta_mm, plus_dir):
    steps = int(round(abs(delta_mm) * STEPS_PER_MM))
    if steps == 0:
        print("  %s 无需移动" % axis)
        return True
    direction = plus_dir if delta_mm > 0 else ("DIR1" if plus_dir == "DIR0" else "DIR0")
    cmd = "MOVE %s %s STEPS %d HZ %d" % (axis, direction, steps, HZ)
    print("  %s (=%+.1f mm)" % (cmd, delta_mm))
    arm = send("MOTION ARM")
    if "OK" not in arm:
        print("    !! ARM 失败，该轴未移动")
        return False
    reply = send(cmd, 0.12)
    lines = [l.strip() for l in reply.splitlines() if "OK" in l or "ERR" in l]
    print("    应答:", lines[0] if lines else "(无)")
    t0 = time.time()
    started, res = False, -1
    while time.time() - t0 < 25.0:
        d = status_fields()
        rv = d.get("STEP_REMAIN", "")
        rem = int(rv) if rv.isdigit() else -1
        if rem > 0:
            started = True
        if started and rem == 0:
            rv2 = d.get("STEP_RESULT", "")
            res = int(rv2) if rv2.isdigit() else -1
            break
        if not started and time.time() - t0 > 4.0:
            break
    if not started:
        print("    !! 没抓到运动（板子可能仍执行了）")
        return False
    print("    到位 %.2fs  STEP_RESULT=%d" % (time.time() - t0, res))
    return res == 1


ok = jog("X", dx, "DIR0")
ok = jog("Y", dy, "DIR1") and ok
s.close()

print("\n=> 夹爪理论真值 = (%.1f, %.1f) mm（若记账有误差，以你目视为准）" % (tgt_x, tgt_y))
print("【请看】夹爪相对物块差多少、往哪边？这个残差直接拿去修 tx/ty。")
sys.exit(0 if ok else 1)
