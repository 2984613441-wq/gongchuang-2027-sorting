#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""听 MaixCAM 一阵子，打印物块像素坐标 + 换算结果 + 相对【已知真值】的误差。

这是唯一算数的测量方式：物块被放在机器已知点上（真值由调用方给出），
读它被算成什么，差多少就是标定误差。

顺带直接给出把误差归零所需的 tx/ty（因为 x = a11*u + tx，改 tx 就是平移）。

用法： python3 pi_read_object.py <true_x_mm> <true_y_mm> [秒数=12]
"""
import socket
import sys
import time

sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter   # noqa: E402
from electrical_control.rpi.vision_ingest import parse_batch_targets        # noqa: E402

CAL = "/home/pi/电控/calibration_config.ini"
conv = PixelToDeviceConverter(CAL)

true_x, true_y = float(sys.argv[1]), float(sys.argv[2])
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0

print("真值 = (%.1f, %.1f) mm    监听 %.0f 秒" % (true_x, true_y, seconds))
def raw_value(key):
    """从配置文件里取原始数值（忽略行内注释）。"""
    with open(CAL, encoding="utf-8") as fh:
        for ln in fh:
            body = ln.split("#", 1)[0].strip()
            if body.startswith(key + " ="):
                return float(body.split("=", 1)[1].strip())
    return float("nan")


print("现行标定: a11=%.6f a12=%.6f tx=%.3f / a21=%.6f a22=%.6f ty=%.3f camera_height=%.1f" %
      (raw_value("a11"), raw_value("a12"), raw_value("tx"),
       raw_value("a21"), raw_value("a22"), raw_value("ty"),
       raw_value("camera_height")))

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 8765))
srv.listen(4)
srv.settimeout(1.0)

seen = {}          # box_id -> (count, pixel_x, pixel_y, device)
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
        # 先读 3 字节头（count + task_id），再按 count 读足长度。
        # 旧写法写死 10 字节，遇到 2 目标的 17 字节帧就错位 → 后面全是垃圾。
        head = recv_n(3)
        if len(head) == 3:
            data = head + recv_n(head[0] * 7)
            if len(data) == 3 + head[0] * 7:
                batch = parse_batch_targets(data)
                for t in batch.targets:
                    got = conv.pixel_to_device(t.pixel_x, t.pixel_y, t.box_id)
                    n, _, _, _ = seen.get(t.box_id, (0, 0, 0, None))
                    seen[t.box_id] = (n + 1, t.pixel_x, t.pixel_y, got)
                    print("  box_id=%d px=%3d py=%3d -> %s" %
                          (t.box_id, t.pixel_x, t.pixel_y, got))
            else:
                print("  (帧不完整: count=%d 只收到 %d 字节)" % (head[0], len(data)))
    except Exception as exc:  # noqa: BLE001
        print("  (读帧失败: %s)" % exc)
    finally:
        conn.close()

srv.close()

print("\n=== 汇总 ===")
if not seen:
    print("  一帧都没收到 —— 物块没被检出（出黄框了？被夹爪挡了？灯关了？）")
    sys.exit(2)

for box_id, (n, px, py, got) in sorted(seen.items()):
    if got is None:
        # 拒识也要给数：直接用仿射原式算一遍，否则出界点什么信息都拿不到。
        # 🔴 必须算全 4 项：图像轴与机器轴错位约 90°，a12/a21 才是主导项。
        #    旧写法只算 a11*px+tx / a22*py+ty，漏掉交叉项 ≈ 46mm，会把正确的
        #    标定报成 46mm 误差 —— 而越界点恰恰是最需要看数的场合。
        rwx = (raw_value("a11") * px + raw_value("a12") * py + raw_value("tx"))
        rwy = (raw_value("a21") * px + raw_value("a22") * py + raw_value("ty"))
        print("  box_id=%d  %d 帧  px=%d py=%d -> 拒识(越界)" % (box_id, n, px, py))
        print("    仿射原式仍算出 (%.2f, %.2f) mm   真值 (%.1f, %.1f) mm" %
              (rwx, rwy, true_x, true_y))
        print("    误差 (Δx=%+.2f, Δy=%+.2f) mm" % (rwx - true_x, rwy - true_y))
        continue
    gx, gy = got[0] / 10.0, got[1] / 10.0
    ex, ey = gx - true_x, gy - true_y
    print("  box_id=%d  %d 帧  px=%d py=%d" % (box_id, n, px, py))
    print("    算出 (%.1f, %.1f) mm   真值 (%.1f, %.1f) mm" % (gx, gy, true_x, true_y))
    print("    误差 (Δx=%+.1f, Δy=%+.1f) mm   |误差|=%.1f mm" % (ex, ey, (ex * ex + ey * ey) ** 0.5))
    print("    若要此点归零：tx += %+.3f , ty += %+.3f" % (-ex, -ey))
