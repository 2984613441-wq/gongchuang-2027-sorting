#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时显示物块像素坐标是否在标定工作区内 —— 一行原地刷新，方便对着调位置。

用法（在树莓派上跑，另开一个终端窗口）：
    cd /home/pi/电控 && sudo PYTHONPATH=src python3 /home/pi/pi_live_object.py

怎么用：看着这一行数，用手移动物块，直到它变成 ✅。
        显示的 px / py 会随你移动实时变化，py 越大表示越靠画面下方。
        目标：px 在 57~232，py 在 142~232。
按 Ctrl+C 退出。
"""
import socket
import sys
import time

sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.vision_ingest import parse_batch_targets        # noqa: E402
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter   # noqa: E402

conv = PixelToDeviceConverter("/home/pi/电控/calibration_config.ini")

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 8765))
srv.listen(4)
srv.settimeout(1.0)

print(__doc__)
print("px 合法 57~232   py 合法 142~232   （py 越大 = 越靠画面下方）")
print()

last = 0.0
while True:
    try:
        conn, _ = srv.accept()
    except socket.timeout:
        if time.time() - last > 3.0:
            print("\r等待视觉数据……（超过 3 秒没帧 = 没检出物体，物块可能出了黄框）",
                  end="", flush=True)
            last = time.time()
        continue
    conn.settimeout(2.0)
    try:
        data = b""
        while len(data) < 10:
            chunk = conn.recv(10 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) >= 10:
            b = parse_batch_targets(data)
            for t in b.targets:
                got = conv.pixel_to_device(t.pixel_x, t.pixel_y, t.box_id)
                px_ok = 57 <= t.pixel_x <= 232
                py_ok = 142 <= t.pixel_y <= 232
                mark = "✅ 可用" if got is not None else "❌ 越界"
                print("\rpx=%3d %s   py=%3d %s   -> %-18r %s   "
                      % (t.pixel_x, "OK" if px_ok else "!!", t.pixel_y,
                         "OK" if py_ok else "!!", got, mark), end="", flush=True)
                last = time.time()
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()
