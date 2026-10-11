#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视野覆盖实测：你挪物块，它把相机看得见的范围（像素）自动圈出来。

只监听 MaixCAM，**完全不碰 STM32**。

用法：
    python3 pi_fov_probe.py            # 追 box_id=1（青色正方体）
    python3 pi_fov_probe.py 3          # 追别的货格号

怎么用：
    1. 把那个物块放在工作台上，**慢慢挪**：先推到你能推到的最左、最右、
       最上、最下（贴着工作台四边）。
    2. 屏幕上会实时显示它的像素坐标，并把见过的【最小/最大】记下来。
    3. 挪完按 Ctrl+C，会打印最终结论：相机实际看到的像素范围。
       → X 跨度越大，视野越宽。若只能在一个窄带里动，就是视野不够。

判读：
    · X 能在 0~319 之间大幅变化  → 相机看得见整个工作台宽度，视野够
    · X 只在很小的范围里动        → 相机只覆盖了工作台一条，需要抬高相机
"""

import socket
import sys
import time
from typing import Optional

PORT = 8765
HEADER = 3
PER_TARGET = 7


def parse(data: bytes):
    if len(data) < 3:
        return None
    count = data[0]
    if len(data) != HEADER + count * PER_TARGET:
        return None
    out = []
    for i in range(count):
        o = HEADER + i * PER_TARGET
        out.append((data[o], data[o + 1],
                    int.from_bytes(data[o + 2:o + 4], "big"),
                    int.from_bytes(data[o + 4:o + 6], "big")))
    return out


def main(box_id: int, seconds: float = 0.0) -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(1)
    srv.settimeout(1.0)

    print("=" * 66)
    print("视野覆盖实测 —— 追踪 box_id=%d，只监听，不碰 STM32" % box_id)
    print("把那个物块贴着工作台四边慢慢挪一圈，松开后按 Ctrl+C 看结论。")
    print("=" * 66)

    conn = None
    frame_w = frame_h = 320
    seen = 0
    miss = 0
    bounds = None  # [minx, maxx, miny, maxy]
    last_print = 0.0
    t0 = time.monotonic()

    try:
        while True:
            if conn is None:
                try:
                    conn, addr = srv.accept()
                    print("\n[MaixCAM 已连接] %s:%d\n" % addr)
                    conn.settimeout(1.0)
                except socket.timeout:
                    print("  ...等 MaixCAM 连进来（在 MaixVision 里跑 stage1_color_v6_send.py）")
                    continue
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                conn = None
                continue
            if not chunk:
                print("[断开] 等待重连...")
                conn = None
                continue

            targets = parse(chunk)
            if targets is None:
                continue
            hit = [t for t in targets if t[0] == box_id]
            if not hit:
                miss += 1
                continue

            seen += 1
            _, conf, px, py = hit[0]
            if bounds is None:
                bounds = [px, px, py, py]
            else:
                bounds[0] = min(bounds[0], px)
                bounds[1] = max(bounds[1], px)
                bounds[2] = min(bounds[2], py)
                bounds[3] = max(bounds[3], py)

            now = time.monotonic()
            if now - last_print >= 0.25:
                last_print = now
                print("  当前 (%3d,%3d) conf=%2d   |  见过的范围 "
                      "X %3d~%3d (跨%3d)   Y %3d~%3d (跨%3d)   [%d帧, 漏%d]"
                      % (px, py, conf,
                         bounds[0], bounds[1], bounds[1] - bounds[0],
                         bounds[2], bounds[3], bounds[3] - bounds[2],
                         seen, miss))
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()

    print("\n" + "=" * 66)
    dt = time.monotonic() - t0
    if bounds is None:
        print("全程【一次都没检出 box_id=%d】" % box_id)
        print("→ 要么物体没在画面里，要么颜色阈值不认它（换个货格号再试）")
        return 1

    span_x = bounds[1] - bounds[0]
    span_y = bounds[3] - bounds[2]
    print("跑了 %.0f 秒，检出 %d 帧，漏 %d 帧" % (dt, seen, miss))
    print("相机看得见的像素范围：")
    print("   X  %3d ~ %3d   跨 %3d 像素（画面宽 %d）  = 画面宽的 %.0f%%"
          % (bounds[0], bounds[1], span_x, frame_w, 100.0 * span_x / frame_w))
    print("   Y  %3d ~ %3d   跨 %3d 像素（画面高 %d）  = 画面高的 %.0f%%"
          % (bounds[2], bounds[3], span_y, frame_h, 100.0 * span_y / frame_h))
    print()
    print("判读：")
    print("  · 跨度接近 300 → 相机看得见工作台全宽，视野够")
    print("  · 跨度只有几十 → 相机只覆盖了工作台一条，需要抬高相机")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    bid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    sys.exit(main(bid))
